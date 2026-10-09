"""A lock per sample_id in Redis.

Held while a sample is created, or fetched from HCP into MongoDB, so that two
requests (or a request and the cleanup job) never work on the same sample at
the same time. Redis makes taking the lock atomic across all API processes.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from redis.exceptions import LockError, RedisError

from .queue import redis

LOG = logging.getLogger(__name__)

KEY_PREFIX = "bonsai:sample-lock:"
POLL_SECONDS = 0.5


class SampleLockError(Exception):
    """The lock for a sample could not be taken (Redis unreachable, or waited too long)."""


@asynccontextmanager
async def sample_lock(sample_id: str, ttl: int) -> AsyncIterator[None]:
    """Hold the lock for one sample while the block runs.

    Waits while another request holds it.

    :param ttl: Seconds after which Redis releases the lock by itself, so a
        crashed process can't block the sample for good. Waiting gives up
        after the same time.
    """
    lock = redis.connection.lock(f"{KEY_PREFIX}{sample_id}", timeout=ttl)
    automatically_unlock_at = time.time() + ttl
    try:
        # a non-blocking attempt per poll, so waiting doesn't block the event loop
        while not lock.acquire(blocking=False):
            if time.time() > automatically_unlock_at:
                raise SampleLockError(f"Timed out waiting for the lock on sample '{sample_id}'")
            await asyncio.sleep(POLL_SECONDS)
    except RedisError as error:
        raise SampleLockError(f"Could not take the lock on sample '{sample_id}': {error}") from error
    try:
        yield
    finally:
        try:
            lock.release()
        except LockError as error:  # also covers a lock that expired while held
            LOG.warning("Lock on sample '%s' was already released: %s", sample_id, error)
        except RedisError as error:
            LOG.warning("Could not release the lock on sample '%s': %s", sample_id, error)

