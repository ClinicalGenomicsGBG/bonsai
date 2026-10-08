"""Sample documents: cached in MongoDB, with the permanent copy in HCP."""

import logging

from bson import ObjectId
from prp.models import PipelineResult
from pymongo.errors import DuplicateKeyError

from ..config import settings
from ..crud.sample import create_sample as create_sample_record
from ..crud.sample import get_samples_summary
from ..db import Database
from ..models.sample import SampleInDatabase
from ..redis.hcp import HcpUploadError, upload_sample_document
from .cached_sample_service import CachedSampleService
from .hci_mock_service import HciMockService

LOG = logging.getLogger(__name__)


class SampleAlreadyExistsError(Exception):
    """A sample with this sample_id is already stored, and duplicates are rejected."""


class RollbackError(Exception):
    """Storing the sample failed, and removing the new MongoDB document failed too."""


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

