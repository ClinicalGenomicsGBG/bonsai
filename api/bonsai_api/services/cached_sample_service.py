"""Keep track of which samples are cached in MongoDB, and when they were last used."""

import logging
from typing import Iterable

from pymongo import ASCENDING, UpdateOne
from pymongo.results import DeleteResult

from ..db import Database
from ..models.cached_sample import CachedSample
from ..utils import get_timestamp

LOG = logging.getLogger(__name__)

COLLECTION = "cached_sample"


class CachedSampleService:
    """Bookkeeping for the sample documents cached in the sample collection.

    The service only touches its own collection; the caller decides when a
    sample counts as cached or accessed.
    """

    # Indexes are created once per process, on first use. Creating them at
    # startup would stop the API from starting while MongoDB is unavailable.
    _indexes_created = False

    def __init__(self, db: Database):
        # self._db = db
        self._collection = db.db[COLLECTION]

    async def _ensure_indexes(self) -> None:
        if CachedSampleService._indexes_created:
            return
        await self._collection.create_index(
            [("sample_id", ASCENDING)], unique=True, name="cached_sample_sample_id"
        )
        await self._collection.create_index(
            [("last_accessed_at", ASCENDING)], name="cached_sample_last_accessed_at"
        )
        CachedSampleService._indexes_created = True

    async def touch(self, sample_ids: str | Iterable[str], username: str | None) -> None:
        """Record that samples were accessed, adding entries for new samples.

        :param sample_ids: One sample id or several.
        :param username: Who accessed them; None on routes without login.
        """
        await self._ensure_indexes()
        ids = [sample_ids] if isinstance(sample_ids, str) else list(dict.fromkeys(sample_ids))
        if not ids:
            return
        now = get_timestamp()
        # One upsert per sample: update the access time, and set cached_at
        # only when the entry is created. The unique index on sample_id keeps
        # one entry per sample even if two requests touch it at once.
        requests = [
            UpdateOne(
                {"sample_id": sample_id},
                {
                    "$set": {"last_accessed_at": now, "last_accessed_by": username},
                    "$setOnInsert": {"cached_at": now},
                },
                upsert=True,
            )
            for sample_id in ids
        ]
        await self._collection.bulk_write(requests, ordered=False)

    async def get(self, sample_id: str) -> CachedSample | None:
        """Get the cache entry for one sample, or None if it isn't cached."""
        await self._ensure_indexes()
        doc = await self._collection.find_one({"sample_id": sample_id}, {"_id": 0})
        return CachedSample.model_validate(doc) if doc else None

    async def cached_ids(self, sample_ids: Iterable[str]) -> set[str]:
        """Return the subset of sample_ids that have a cache entry."""
        await self._ensure_indexes()
        cursor = self._collection.find(
            {"sample_id": {"$in": list(sample_ids)}}, {"_id": 0, "sample_id": 1}
        )
        return {doc["sample_id"] async for doc in cursor}


    async def expired_ids(self, cutoff) -> list[str]:
        """Return list of sample_ids for expired cache entries

        :param cutoff: entries last accessed before this `datetime` count as expired
        :type cutoff: datetime
        :return: sample_ids of expired cache entries
        :rtype: list[str]
        """
        await self._ensure_indexes()
        cursor = self._collection.find(
            {
                "last_accessed_at": {"$lt": cutoff}
            },
            {
                "_id": 0,
                "sample_id": 1
            }
        )
        docs = [doc["sample_id"] async for doc in cursor]
        return docs


    async def delete_cached_sample(self, sample_id: str) -> DeleteResult:
        """Delete cached sample from the cache

        :param sample_id: Sample ID of cached sample to delete.
        :type sample_id: str
        :return: the result of the delete operation
        :rtype: DeleteResult
        """

        return await self._collection.delete_one({ "sample_id": sample_id })

