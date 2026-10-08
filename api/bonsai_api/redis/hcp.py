import asyncio
import json
import logging
import time
from typing import Any

from redis.exceptions import RedisError

from ..config import settings
from .queue import redis

LOG = logging.getLogger(__name__)


class HcpUploadError(Exception):
    """The HCP upload worker reported a failure"""

class HcpUploadTimeout(HcpUploadError):
    """The HCP upload worker timed out"""

class HcpQueueUnavailable(HcpUploadError):
    """The HCP upload jobs could not be submitted (Redis unreachable)"""


TASK = "hci_hcp_service.tasks.upload_sample"
# Extra time the API keeps polling after the deadline it gives the worker.
# Covers the polling interval and small clock differences between containers.
GRACE_SECONDS = 5
POLL_SECONDS = 0.5


async def upload_sample_document(document: dict[str, Any], overwrite: bool = False) -> dict[str, Any]:
    "Upload one sample document to the HCP and wait for the worker's result"

    timeout_deadline = time.time() + settings.hcp_upload_timeout

    try:
        job = redis.hcp.enqueue(
            TASK,
            document=json.dumps(document),
            deadline=timeout_deadline,
            overwrite=overwrite,
            job_timeout=settings.hcp_upload_timeout,
            result_ttl=3600,
            failure_ttl=86400,
        )
    except RedisError as error:
        raise HcpQueueUnavailable(f"Could not submit upload job: {error}") from error

    while time.time() < timeout_deadline + GRACE_SECONDS:
        try:
            # Statuses:
            # - canceled: Job was manually canceled
            # - deferred: job has NOT started, waiting on its dependencies
            # - failed: job encountered an error during execution, or timed out
            # - finished: Job has finished execution and its value can be returned
            # - started: job has started execution
            # - stopped: Job was stopped because the worker was stopped
            job_status = job.get_status(refresh=True)

            if job_status == "finished":
                return job.return_value()

            if job_status in ("failed", "canceled", "stopped"):
                # exc_info is the worker's full traceback (None if the job was canceled or stopped)
                reason = (job.exc_info or job_status).strip().splitlines()[-1]
                # More manageable error message:
                LOG.debug("HCP upload job '%s' '%s': %s", job.id, job_status, reason)
                # Full stacktrace:
                # LOG.debug("HCP upload job %s failed: %s", job.id, job.exc_info, reason)
                raise HcpUploadError(reason)
        except RedisError as error:
            raise HcpQueueUnavailable(f"Lost Redis while waiting for job '{job.id}': {error}") from error

        await asyncio.sleep(POLL_SECONDS)

    raise HcpUploadTimeout(
        "The HCP upload worker did not return a result within "
        f"{settings.hcp_upload_timeout} s for job with id: '{job.id}'"
    )

