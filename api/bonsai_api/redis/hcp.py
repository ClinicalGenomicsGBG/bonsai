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

class HcpUploadQueueUnvailable(HcpUploadError):
    """The HCP upload jobs could not be submitted (Redis unreachable)"""

class HcpDownloadError(Exception):
    """The HCP download worker reported a failure"""

class HcpDownloadTimeout(HcpDownloadError):
    """The HCP download worker timed out"""

class HcpDownloadQueueUnavailable(HcpDownloadError):
    """The HCO download jobs could not be submitted (Redis unreachable)"""


UPLOAD_TASK = "hci_hcp_service.tasks.upload_sample"
DOWNLOAD_TASK = "hci_hcp_service.tasks_download_sample"
# Extra time the API keeps polling after the deadline it gives the worker.
# Covers the polling interval and small clock differences between containers.
GRACE_SECONDS = 5
POLL_SECONDS = 0.5


async def _wait_for_job(
    job,
    timeout_deadline: float,
    timeout_seconds: int,
    kind: str,
    failed_error: type[Exception],
    timeout_error: type[Exception],
    queue_error: type[Exception],
) -> Any:
    """Poll an HCP worker job until it has a result, failed, or the deadline passed.

    :param kind: "upload" or "download", used in messages.
    :param failed_error: Raised when the job failed, was canceled or stopped.
    :param timeout_error: Raised when there's no result before the deadline.
    :param queue_error: Raised when Redis is lost while waiting.
    """
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
                LOG.debug("HCP %s job '%s' '%s': %s", kind,  job.id, job_status, reason)
                # Full stacktrace:
                # LOG.debug("HCP upload job %s failed: %s", job.id, job.exc_info, reason)
                raise failed_error(reason)
        except RedisError as error:
            raise queue_error(
                f"Lost Redis while waiting for {kind} job with id '{job.id}': {error}"
            ) from error

        await asyncio.sleep(POLL_SECONDS)

    raise timeout_error(
        "The HCP {kind} worker did not return a result within "
        f"{timeout_seconds} s for job with id: '{job.id}'"
    )


async def upload_sample_document(document: dict[str, Any], overwrite: bool = False) -> dict[str, Any]:
    """Upload one sample document to the HCP and wait for the worker's result"""

    timeout_deadline = time.time() + settings.hcp_upload_timeout

    try:
        job = redis.hcp.enqueue(
            UPLOAD_TASK,
            document=json.dumps(document),
            deadline=timeout_deadline,
            overwrite=overwrite,
            job_timeout=settings.hcp_upload_timeout,
            result_ttl=3600,
            failure_ttl=86400,
        )
    except RedisError as error:
        raise HcpUploadQueueUnvailable(f"Could not submit upload job: {error}") from error

    document = await _wait_for_job(
        job,
        timeout_deadline,
        settings.hcp_upload_timeout,
        "upload",
        HcpUploadError,
        HcpUploadTimeout,
        HcpUploadQueueUnvailable,
    )

    return document


async def download_sample_document(hcp_key: str) -> dict[str, Any]:
    """Download one sample document from the HCP and wait for the worker's result"""
    timeout_deadline = time.time() + settings.hcp_download_timeout

    try:
        job = redis.hcp.enqueue(
            DOWNLOAD_TASK,
            hcp_key=hcp_key,
            deadline=timeout_deadline,
            job_timeout=settings.hcp_download_timeout,
            result_ttl=3600,
            failure_ttl=86400,
    )
    except RedisError as error:
        raise HcpDownloadQueueUnavailable(f"Could not submit download job: {error}") from error

    document = await _wait_for_job(
        job,
        timeout_deadline,
        settings.hcp_download_timeout,
        "download",
        HcpDownloadError,
        HcpDownloadTimeout,
        HcpDownloadQueueUnvailable,
    )

    return json.loads(document)

