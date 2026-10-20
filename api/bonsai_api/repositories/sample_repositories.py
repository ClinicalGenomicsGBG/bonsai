from abc import ABC, abstractmethod

from ..db import Database
from .cached_sample_service import CachedSampleService
from .hci_mock_service import HciMockServiceService


@abstract
class SampleRepositoryInterface(ABC):
    """
    SampleRepisitory base/contract/interface
    """
    @abstractmethod
    async def count_documents(_filter, limit):
        ...

    @abstractmethod
    async def find_one(_filter, projection, options):
        ...

class SampleMongoDbRepository(SampleRepositoryInterface):
    def __init__(
            self,
            db: Database,
            cached_samples: CachedSampleService,
            hci_mock: HciMockService,
    ):
    self._db = db
    self._cached_samples
    self._hci_mock = hci_mock

    async def count_documents(_filter, limit: int):
        return await self._db.sample_collection.count_documents(
            _filter,
            limit=limit,
        )


    async def find_one(_filter, projection, options):
        return await self._db.sample_collection.find_one(
            _filter,
            projection,
            options,
        )
