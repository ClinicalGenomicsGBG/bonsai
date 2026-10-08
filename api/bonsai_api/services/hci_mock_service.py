"""Mock of the HCI index: a permanent record of every sample uploaded to HCP.

Stands in for the real HCI until that is integrated. It lives in its own
database (settings.hci_mock_database_name) because it represents an external
system and must survive cleanup of the MongoDB sample cache.
"""

import logging
from typing import Any

from pymongo import ASCENDING

from ..config import settings
from ..db import Database
from ..models.hci_mock import HciMockEntry
from ..utils import get_timestamp

LOG = logging.getLogger(__name__)

COLLECTION = "sample"


class HciMockService:
    """Register uploaded samples and look them up, like an HCI index would."""

    # Indexes are created once per process, on first use (see CachedSampleService).
    _indexes_created = False

    def __init__(self, db: Database):
        self._collection = db.client[settings.hci_mock_database_name][COLLECTION]

    async def _ensure_indexes(self) -> None:
        if HciMockService._indexes_created:
            return
        await self._collection.create_index(
            [("sample_id", ASCENDING)], unique=True, name="hci_mock_sample_id"
        )
        HciMockService._indexes_created = True

    async def register(
        self,
        sample_id: str,
        bucket: str,
        key: str,
        summary: dict[str, Any],
        overwrite: bool = True,
    ) -> None:
        """Add or update the index entry for a sample stored in HCP.

        :param summary: The sample's row for the groups pages.
        :param overwrite: Replace an existing entry. Use False when the upload
            was skipped because the object already existed, so the entry keeps
            describing the object that is actually in HCP.
        """
        await self._ensure_indexes()
        fields = {
            "hcp_bucket": bucket,
            "hcp_key": key,
            "summary": summary,
            "registered_at": get_timestamp(),
        }
        update = {"$set": fields} if overwrite else {"$setOnInsert": fields}
        await self._collection.update_one({"sample_id": sample_id}, update, upsert=True)

    async def get(self, sample_id: str) -> HciMockEntry | None:
        """Look up one sample, or None if it was never uploaded."""
        await self._ensure_indexes()
        doc = await self._collection.find_one({"sample_id": sample_id}, {"_id": 0})
        return HciMockEntry.model_validate(doc) if doc else None

    async def find(
        self, sample_ids: list[str] | None = None, limit: int = 0, skip: int = 0
    ) -> list[HciMockEntry]:
        """List indexed samples, optionally only the given ones (for the groups pages)."""
        await self._ensure_indexes()
        query = {} if sample_ids is None else {"sample_id": {"$in": sample_ids}}
        cursor = self._collection.find(query, {"_id": 0}).sort("sample_id", ASCENDING)
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        return [HciMockEntry.model_validate(doc) async for doc in cursor]

