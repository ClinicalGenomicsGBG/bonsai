"""Debug view of the sample cache (development only, see settings.debug_views)."""

from typing import Any

from fastapi import APIRouter, Depends, Security

from ..config import settings
from ..crud.user import get_current_active_user
from ..db import Database, get_db
from ..models.user import UserOutputDatabase

router = APIRouter(prefix="/debug", tags=["debug"])

READ_PERMISSION = "samples:read"


@router.get("/cache")
async def cache_overview(
    db: Database = Depends(get_db),
    current_user: UserOutputDatabase = Security(  # pylint: disable=unused-argument
        get_current_active_user, scopes=[READ_PERMISSION]
    ),
) -> dict[str, list[dict[str, Any]]]:
    """What MongoDB, cached_sample and the HCI mock contain, side by side.

    Reads the collections directly, which is fine for a debug view only.
    """
    samples = db.sample_collection.find({}, {"sample_id": 1, "created_at": 1})
    cached = db.db["cached_sample"].find({}, {"_id": 0})
    hci_mock = db.client[settings.hci_mock_database_name]["sample"].find(
        {}, {"_id": 0, "summary": 0}
    )
    return {
        "samples": [{**doc, "_id": str(doc["_id"])} async for doc in samples],
        "cached_samples": [doc async for doc in cached],
        "hci_mock": [doc async for doc in hci_mock],
    }
