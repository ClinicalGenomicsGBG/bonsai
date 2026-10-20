"""Sample cleanup operations"""

import logging
from datetime import timedelta, timezone

from ..redis.sample_lock import sample_lock
from ..config import settings
# from ..db import Database
from ..utils import get_timestamp
from .sample_service import SampleService
from .cached_sample_service import CachedSampleService

LOG = logging.getLogger(__name__)

# COLLECTION = "cached_sample"


class CacheCleanupService:
    """Removes samples from the MongoDB cache when their cache entry
    has expired or they have no entry. Never touches HCP or the HCI mock."""
    def __init__(self,
         # db: Database,
         sample_service: SampleService,
         cached_service: CachedSampleService,
    ):
        self._sample_service = sample_service
        self._cached_sample_service = cached_service


    async def run_cleanup(self):
        """Remove samples from MongoDB that the cache no longer allows to be kept.

        A sample is a candidate if its cached_sample entry has expired (last
        accessed more than settings.sample_cache_ttl_minutes ago), or if it is
        in MongoDB without a cache entry at all.

        Each candidate is handled under its sample lock, taken without waiting:

        - If the lock is busy, a request is creating or fetching the sample, so
          it is skipped until the next round.
        - Otherwise the cache entry is read again. If the sample has been
          accessed since the cutoff, it is kept.
        - Else the sample is deleted from MongoDB first (its documents, group
          memberships and minhash signature; see SampleService.delete_samples),
          then its cache entry. If the round fails in between, the expired entry
          remains, and the next round completes the removal.

        HCP and the HCI mock are never touched. Logs how many samples were
        removed and how many were skipped because their lock was busy.
        """
        cutoff = get_timestamp() - timedelta(minutes=settings.sample_cache_ttl_minutes)
        samples_in_mongodb: set[str] = await self._sample_service.get_all_distinct_sample_ids()
        untracked_samples: set[str] = (
            samples_in_mongodb - await self._cached_sample_service.cached_ids(samples_in_mongodb)
        )
        expired_samples: set[str] = set(
            await self._cached_sample_service.expired_ids(cutoff)
        )
        candidates = expired_samples | untracked_samples
        # LOG.info("samples_in_mongodb (count: %s): %s", len(samples_in_mongodb), samples_in_mongodb)
        # LOG.info("untracked_samples (count: %s): %s", len(untracked_samples), untracked_samples)
        # LOG.info("expired_samples (count: %s): %s", len(expired_samples), expired_samples)
        # LOG.info("candidates (count: %s): %s", len(candidates), candidates)

        skipped_samples = 0
        removed_samples = 0

        for sample_id in candidates:
            async with sample_lock(sample_id, ttl=settings.cache_cleanup_lock_ttl_seconds, wait=False) as acquired:
                if not acquired:
                    skipped_samples += 1
                    continue
                cache_entry = await self._cached_sample_service.get(sample_id)
                # The sample may have accessed since we last looked, if so leave it alone
                if (
                    cache_entry
                    and
                    cache_entry.last_accessed_at.replace(tzinfo=timezone.utc) >= cutoff
                ):
                    continue

                # Attempt to delete the sample's document from the MongoDB first.
                await self._sample_service.delete_samples([sample_id])

                # Attempt to remove the sample from the cache tracking database.
                await self._cached_sample_service.delete_cached_sample(sample_id)

                removed_samples += 1

        LOG.info(
            "Dr. Jan Itor cleaned up %d & skipped %d (due to Redis lock) samples",
            removed_samples,
            skipped_samples,
        )
