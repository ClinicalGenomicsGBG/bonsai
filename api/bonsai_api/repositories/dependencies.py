"""FastAPI providers for the services (use with Depends)."""

from fastapi import Depends

from .sample_repositories import SampleMongoDbRepository, SampleRepositoryInterface


# def get_cachedsample_service(db: Database = Depends(get_db)) -> CachedSampleService:
#     """Provide a CachedSampleService using the request's database connection."""
#     return CachedSampleService(db)
#
#
# def get_hci_mock_service(db: Database = Depends(get_db)) -> HciMockService:
#     """Provide an HciMockService using the request's database connection."""
#     return HciMockService(db)


def get_sample_repository(
    db: Database = Depends(get_db),
    cached_samples: CachedSampleService = Depends(get_cached_sample_service),
    hci_mock: HciMockService = Depends(get_hci_mock_service),
) -> SampleRepositoryInterface:
    

