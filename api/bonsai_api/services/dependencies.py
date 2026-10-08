"""FastAPI providers for the services (use with Depends)."""

from fastapi import Depends

from ..db import Database, get_db
from .cached_sample_service import CachedSampleService
from .hci_mock_service import HciMockService
from .sample_service import SampleService


def get_cached_sample_service(db: Database = Depends(get_db)) -> CachedSampleService:
    """Provide a CachedSampleService using the request's database connection."""
    return CachedSampleService(db)


def get_hci_mock_service(db: Database = Depends(get_db)) -> HciMockService:
    """Provide an HciMockService using the request's database connection."""
    return HciMockService(db)


def get_sample_service(
    db: Database = Depends(get_db),
    cached_samples: CachedSampleService = Depends(get_cached_sample_service),
    hci_mock: HciMockService = Depends(get_hci_mock_service),
) -> SampleService:
    """Provide a SampleService using the request's database connection."""
    return SampleService(db, cached_samples, hci_mock)

