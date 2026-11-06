"""Routes for interacting with submitted jobs."""

import logging

from fastapi import APIRouter, Security, status

from ..crud.user import get_current_active_user
from ..models.user import UserOutputDatabase
from ..redis.queue import JobStatus, check_redis_job_status

LOG = logging.getLogger(__name__)

DEFAULT_TAGS = [
    "jobs",
]
READ_PERMISSION = "job:read"
WRITE_PERMISSION = "job:write"
# No role has the job:* permissions, so reading job results requires
# samples:read: results contain sample data (cluster trees, downloaded samples).
SAMPLES_READ_PERMISSION = "samples:read"

router = APIRouter()


@router.get("/job/status/{job_id}", status_code=status.HTTP_200_OK, tags=DEFAULT_TAGS)
async def check_job_status(
    job_id: str,
    current_user: UserOutputDatabase = Security(  # pylint: disable=unused-argument
        get_current_active_user, scopes=[SAMPLES_READ_PERMISSION]
    ),
) -> JobStatus:
    """Entrypoint for checking status of running jobs.

    :param job_id: Redis job id
    :type job_id: str
    :return: Job information.
    :rtype: JobStatus
    """
    info = check_redis_job_status(job_id=job_id)
    return info
