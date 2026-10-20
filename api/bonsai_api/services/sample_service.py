"""Sample documents: cached in MongoDB, with the permanent copy in HCP."""

import logging

from bson import ObjectId
from prp.models import PipelineResult
from pymongo.errors import DuplicateKeyError
from typing import Any

from ..config import settings
from ..crud.sample import create_sample as create_sample_record
from ..crud.sample import get_sample, get_samples_summary
from ..db import Database
from ..models.sample import SampleInDatabase
from ..redis.hcp import HcpUploadError, download_sample_document, upload_sample_document
from ..redis.sample_lock import sample_lock, SampleLockError
from .cached_sample_service import CachedSampleService
from .hci_mock_service import HciMockService
from ..redis.minhash import (
    schedule_remove_genome_signature,
    schedule_remove_genome_signature_from_index,
)
from ..utils import get_timestamp
from ..crud.errors import EntryNotFound


LOG = logging.getLogger(__name__)

# Extra seconds a sample's lock lives beyond the HCP timeout, for the MongoDB work around it
LOCK_MARGIN_SECONDS = 30


class SampleAlreadyExistsError(Exception):
    """A sample with this sample_id is already stored, and duplicates are rejected."""


class RollbackError(Exception):
    """Storing the sample failed, and removing the new MongoDB document failed too."""


class SampleNotFoundError(EntryNotFound):
    """The sample is neither chached in MongoDB nor recorded in the HCI mock"""


class SampleRestoreError(Exception):
    """The sample's HCP entry cannot be written to MongoDB"""


class SampleService:
    """Create samples in MongoDB and HCP as one unit.

    Uses the other services for their collections instead of accessing them
    directly.
    """

    def __init__(
        self, db: Database, cached_samples: CachedSampleService, hci_mock: HciMockService
    ):
        self._db = db
        self._cached_samples = cached_samples
        self._hci_mock = hci_mock

    async def create(self, sample: PipelineResult, username: str | None) -> SampleInDatabase:
        """Store a new sample in MongoDB and HCP, or in neither.

        If a sample with the same sample_id already exists,
        settings.sample_duplicate_policy decides what happens: "reject" raises
        SampleAlreadyExistsError, "replace" replaces the old sample in MongoDB,
        HCP and the HCI mock.

        :param username: Who uploaded the sample; None without login.
        :raises SampleAlreadyExistsError: The sample exists and the policy is "reject".
        :raises HcpUploadError: The HCP upload failed (subclasses tell why); the
            new MongoDB document has been removed again.
        :raises RollbackError: The upload failed and removing the new document failed too.
        """
        async with sample_lock(sample.sample_id, settings.hcp_upload_timeout + LOCK_MARGIN_SECONDS):
            return await self._create(sample, username)


    async def _create(self, sample: PipelineResult, username: str | None) -> SampleInDatabase:
        """Create the sample (see create); the caller holds the sample's lock"""
        replace = settings.sample_duplicate_policy == "replace"
        if not replace and await self._exists(sample.sample_id):
            raise SampleAlreadyExistsError(f"Sample {sample.sample_id} already exists")
        try:
            db_obj = await create_sample_record(self._db, sample)
        except DuplicateKeyError as error:
            raise SampleAlreadyExistsError(error.details["errmsg"]) from error
        hcp_result = None
        if settings.hcp_upload_enabled:
            hcp_result = await self._upload_to_hcp_or_rollback(db_obj.id, overwrite=replace)

        # Sample was successffully uploaded to
        if replace:
            try:
                # one document per sample_id: drop the ones the new document replaces
                await self._db.sample_collection.delete_many(
                    {"sample_id": db_obj.sample_id, "_id": {"$ne": ObjectId(db_obj.id)}}
                )
            except Exception as error:  # pylint: disable=broad-except
                LOG.error("Could not remove replaced documents of %s: %s", db_obj.sample_id, error)
        try:
            await self._cached_samples.touch(db_obj.sample_id, username)
        except Exception as error:
            LOG.error("Could not record '%s' as cached: %s", db_obj.sample_id, error)
        if hcp_result is not None:
            try:
                await self._register_in_hci_mock(db_obj, hcp_result)
            except Exception as error:  #pylint: disable=broad-except
                LOG.error(
                    "Could not register %s in the HCI mock: %s",
                    db_obj.sample_id,
                    error,
                )
        return db_obj

    async def _read_if_cached(self, sample_id: str) -> SampleInDatabase | None:
        """The sampple from MongoDB if cached_sample has it and the document exists, else None"""
        sample = await self._cached_samples.get(sample_id)
        if sample is None:
            return None

        try:
            return await get_sample(self._db, sample_id)
        except EntryNotFound:
            LOG.info("Cache entry for '%s' is stale; no document in MongoDB", sample_id)


    async def get(self, sample_id: str, username: str | None) -> SampleInDatabase:
        """Get a sample, fetching it from the HCP if it isn't already cached in 'cached_sample'

        cached_sample decides whether the sample should be in MongoDB. Without
        an entry, or with a stale one (no document in MongoDB), the HCP copy is
        downloaded and written to MongoDB, replacing any local document with
        the same sample_id, and the entry is updated.

        :param username: Who requested the sample; None without login.
        :raises SampleNotFoundError: The sample is neither cached nor in the HCI mock.
        :raises HcpDownloadError: The download failed (subclasses tell why).
        :raises SampleRestoreError: The HCP copy can't be written to MongoDB.
        :raises SampleLockError: The sample's lock couldn't be taken.
        """
        LOG.debug("Sample with id '%s' was requested by '%s'", sample_id, username)
        sample = await self._read_if_cached(sample_id)

        if sample is not None:
            LOG.debug("Sample with '%s' found in cache", sample_id)
            self._touch(sample_id, username)
            LOG.debug("===== Sample START =====================================")
            print(sample)
            LOG.debug("===== Sample START =====================================")
            return sample

        async with sample_lock(sample_id, settings.hcp_download_timeout + LOCK_MARGIN_SECONDS):

            # Another request may have cached the sample while waiting for the lock
            sample = await self._cached_samples.get(sample_id)

            if sample is None:
                sample = self._fetch_sample_from_hcp(sample_id)
                # Write the sample to the cached_samples tracker

            self._touch(sample_id, username)

        LOG.debug("Returning sample with id '%s'", sample_id)
        return sample


    async def _touch(self, sample_id: str, username: str | None) -> None:
        """Update cached_samples"""
        try:
            await self._cached_samples.touch(sample_id, username)
        except Exception as error:  # pylint: disable=broad-except
            LOG.error("Could not record '%s' as cached: %s", sample_id, error)



    async def _fetch_sample_from_hcp(self, sample_id: str) -> SampleInDatabase:
        """Fetch sample from the HCP and insert into the MongoDB,
        the caller holds the Redis lock"""
        hci_entry = await self._hci_mock.get(sample_id)
        if hci_entry is None:
            raise SampleNotFoundError(f"Sample '{sample_id} is neither cached nor in HCP")
        LOG.info("Fetching '%s' from HCP (key: '%s')", sample_id, entry.hcp_key)
        document = await download_sample_document(entry.hcp_key)
        # Insert the downloaded sample into the local DB and cache
        await self._restore(sample_id, document)
        # Get the document from the local DB
        sample = await get_sample(self._db, sample_id)


    async def _exists(self, sample_id: str) -> bool:
        """True if the sample is cached in MongoDB or recorded in the HCI mock (i.e. in HCP)."""
        if await self._db.sample_collection.count_documents({"sample_id": sample_id}, limit=1):
            return True
        return await self._hci_mock.get(sample_id) is not None

    async def _register_in_hci_mock(
        self,
        db_obj: SampleInDatabase,
        hcp_result: dict,
    ) -> None:
        """Register an uploaded (to HCP) in the local HCI-mock DB."""
        summary = await get_samples_summary(
            self._db, include_samples=[db_obj.sample_id], prediction_result=True, qc_metrics=True
        )
        row = next((r for r in summary.data if r.get("id") == db_obj.id), None)
        await self._hci_mock.register(
            db_obj.sample_id,
            bucket=hcp_result["bucket"],
            key=hcp_result["key"],
            summary=row or {},
            overwrite=hcp_result["uploaded"],
        )

    async def _restore(self, sample_id: str, document: dict) -> None:
        """Write a sample's HCP copy to MongoDB under its original _id.

        Replaces the local documents of the same sample, never a document of another sample
        """
        if document.get("sample_id") != sample_id:
            raise SampleRestoreError(
                f"The HCP copy for '{sample_id}' belongs to sample '{document.get('sample_id')}'"
            )
        object_id = ObjectId(document["_id"])
        existing = await self._db.sample_collection.find_one({"_id": object_id}, {"sample_id": 1})
        if existing is not None and existing.get("sample_id") != sample_id:
            raise SampleRestoreError(
                f"Can't restore '{sample_id}': its _id {object_id} belongs to sample '{existing.get('sample_id')}'"
            )
        # one document per sample_id: drop the local versions the HCP copy replaces
        await self._db.sample_collection.delete_many(
            {"sample_id": sample_id, "_id": {"$ne": object_id}}
        )
        try:
            # the filter only matches a document of the same sample; otherwise it inserts
            await self._db.sample_collection.replace_one(
                {"_id": object_id, "sample_id": sample_id},
                {**document, "_id": object_id},
                upsert=True,
            )
        except DuplicateKeyError as error:
            # the _id was taken by another sample in the meantime: don't overwrite it
            raise SampleRestoreError(
                f"Can't restore '{sample_id}': its _id {object_id} belongs to another sample"
            ) from error



    async def _upload_to_hcp_or_rollback(self, inserted_id: str, overwrite: bool) -> dict:
        """
        Upload 'sample' document to HCP, and rollback (delete from the MongoDB) if
        the HCP-upload fails.

        :param overwrite: Replace an existing HCP object. Without it, an
            existing object counts as a duplicate.
        """
        object_id = ObjectId(inserted_id)
        sample_doc = await self._db.sample_collection.find_one({"_id": object_id})
        sample_doc["_id"] = str(sample_doc["_id"])

        try:
            # Enqueue a job to upload the document
            LOG.debug("trying to upload sample to hcp")
            result = await upload_sample_document(sample_doc, overwrite=overwrite)
            if not result["uploaded"]:
                # the object is already in HCP and wasn't replaced
                raise SampleAlreadyExistsError(
                    f"Sample {sample_doc['sample_id']} is already in HCP ({result['key']})"
                )
        except (HcpUploadError, SampleAlreadyExistsError) as hcp_upload_error:
            LOG.error(
                "HCP upload failed for %s: %s",
                sample_doc['sample_id'],
                hcp_upload_error
            )
            try:
                await self._db.sample_collection.delete_one({"_id": object_id})
                LOG.info("Sample with id: '%s' was delete from the MongoDB.", inserted_id)
            except Exception as rollback_error:
                LOG.critical(
                    "Rollback of sample document with id: '%s' failed: %s",
                    inserted_id,
                    rollback_error,
                )
                raise RollbackError(
                    f"HCP upload failed, and the MongoDB rollback failed for document: '{inserted_id}'"
                ) from hcp_upload_error
            raise

        LOG.info("Sample %s was uploaded to NGPr, result: %s", sample_doc["sample_id"], result)
        return result


    async def get_all_distinct_sample_ids(self) -> set[str]:
        return set(await self._db.sample_collection.distinct("sample_id"))


    async def delete_samples(self, sample_ids: list[str]) -> dict[str, Any]:
        """Delete a sample from the database, remove it from groups, and remove its signature."""

        result = {
            "sample_ids": sample_ids,
            "n_deleted": 0,
            "removed_from_n_groups": 0,
            "remove_signature_jobs": None,
            "update_index_job": None,
        }
        query_filter = {
            "sample_id": {
                "$in": sample_ids
            }
        }
        # resp = self._db.sample_collection.find(query_filter).to_list(100)
        # result["n_deleted"] = await self._db.sample_collection.count_documents(query_filter)
        # return result
        # remove sample from database
        resp = await self._db.sample_collection.delete_many(query_filter)
        # verify that only one sample found and one document was modified
        result["n_deleted"] = resp.deleted_count
        all_deleted = resp.deleted_count == len(sample_ids)
        LOG.info("Removing samples: %s; status: %s", ", ".join(sample_ids), all_deleted)

        # remove sample from group if sample was deleted
        resp = await self._db.sample_group_collection.update_many(
            {"included_samples": {"$in": sample_ids}},  # filter
            {
                "$pull": {
                    "included_samples": {"$in": sample_ids}
                },  # remove samples from group
                "$set": {"modified_at": get_timestamp()},  # update modified at
            },
        )
        # verify that number of modified groups and samples match
        result["removed_from_n_groups"] = resp.modified_count
        LOG.info(
            "Removing sample %s from groups; in n groups: %d; n modified documents: %d",
            ", ".join(sample_ids),
            resp.matched_count,
            resp.modified_count,
        )

        # remove signature from database and reindex database
        if result["n_deleted"] > 0:
            # remove signatures
            job_ids = []
            for sample_id in sample_ids:
                submitted_job = schedule_remove_genome_signature(sample_id)
                job_ids.append(submitted_job.id)
            result["remove_signature_jobs"] = job_ids
            # remove reindex
            index_job = schedule_remove_genome_signature_from_index(
                sample_ids, depends_on=job_ids
            )
            result["update_index_job"] = index_job.id
        return result
