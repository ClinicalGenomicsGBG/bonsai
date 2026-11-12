"""Entrypoints for starting clustering jobs."""

import logging
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Security, status
from pydantic import ConfigDict, Field

from ..config import settings
from ..crud.errors import EntryNotFound
from ..crud.sample import (
    TypingProfileOutput,
    ensure_sample_in_database,
    get_signature_path_for_samples,
    get_ska_index_path_for_samples,
    get_typing_profiles,
)
from ..crud.user import get_current_active_user
from ..db import Database, get_db
from ..models.base import RWModel
from ..models.cluster import DistanceMethod, TypingMethod
from ..models.user import UserOutputDatabase
from ..redis import ClusterMethod, MsTreeMethods, SubmittedJob
from ..redis.allele_cluster import (
    schedule_cluster_samples as schedule_allele_cluster_samples,
)
from ..redis.minhash import schedule_add_genome_signature_to_index
from ..redis.minhash import schedule_cluster_samples as schedule_minhash_cluster_samples
from ..redis.ska import schedule_cluster_samples as schedule_ska_cluster_samples
from ..redis.hcp import HcpDownloadError, HcpDownloadQueueUnavailable, HcpDownloadTimeout
from ..redis.sample_lock import SampleLockError
from ..services import SampleService
from ..services.dependencies import get_sample_service
from ..services.sample_service import SampleRestoreError

LOG = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_TAGS = [
    "cluster",
]
READ_PERMISSION = "cluster:read"
WRITE_PERMISSION = "cluster:write"
# No role has the cluster:* permissions, so clustering requires samples:read,
# like reading the samples it clusters.
SAMPLES_READ_PERMISSION = "samples:read"


class ClusterInput(RWModel):  # pylint: disable=too-few-public-methods
    """Input data model for cluster entrypoint

    :param RWModel: Generic read write base model
    :type RWModel: Generic basemodel for read/ write
    """

    sample_ids: list[str] = Field(
        ..., min_length=2, max_length=settings.cluster_max_samples, alias="sampleIds"
    )
    distance: DistanceMethod | None = None
    method: ClusterMethod | MsTreeMethods

    model_config = ConfigDict(use_enum_values=False)


@router.post(
    "/cluster/{typing_method}",
    status_code=status.HTTP_201_CREATED,
    response_model=SubmittedJob,
    tags=["minhash", *DEFAULT_TAGS],
)
async def cluster_samples(
    typing_method: TypingMethod,
    cluster_input: ClusterInput,
    db: Database = Depends(get_db),
    samples: SampleService = Depends(get_sample_service),
    current_user: UserOutputDatabase = Security(
        get_current_active_user, scopes=[SAMPLES_READ_PERMISSION]
    ),
) -> SubmittedJob:
    """Cluster samples on their cgmlst profile.

    In order to cluster the samples, all samples need to have a profile and be of the same specie.

    :param typing_method: clustering typing method
    :type typing_method: TypingMethod
    :param cluster_input: clustering input data
    :type cluster_input: ClusterInput
    :raises HTTPException: Raised if some sample was not found
    :return: Information on scheduled job
    :rtype: SubmittedJob
    """
    ####
    # for sample_id in cluster_input.sample_ids:
    #     await ensure_sample_in_database(db, sample_id)
    # Make sure every sample is cached, fetching missing ones from HCP with the
    # same lock and cache bookkeeping as GET /samples/{sample_id}.
    ####

    try:
        username = current_user.username if current_user else None
        # One HCI search for all uncached samples, then each is fetched under its own lock
        await samples.get_many(cluster_input.sample_ids, username)
    except EntryNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except SampleRestoreError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error),
        ) from error
    except SampleLockError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except HcpDownloadError as hcp_download_error:
        if isinstance(hcp_download_error, HcpDownloadTimeout):
            code = status.HTTP_504_GATEWAY_TIMEOUT
        elif isinstance(hcp_download_error, HcpDownloadQueueUnavailable):
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            code = status.HTTP_502_BAD_GATEWAY
        raise HTTPException(
            status_code=code,
            detail=(
                f"Sample '{getattr(hcp_download_error, 'sample_id', '?')}' not cached, "
                f"HCP download failed: {hcp_download_error}"
            ),
        ) from hcp_download_error

    if typing_method == TypingMethod.MINHASH:
        job = schedule_minhash_cluster_samples(
            cluster_input.sample_ids, cluster_input.method
        )
    elif typing_method == TypingMethod.SKA:
        # query database for index file paths using the sample ids and distpatch cluster job to queue
        index_files = await get_ska_index_path_for_samples(db, cluster_input.sample_ids)
        job = schedule_ska_cluster_samples(index_files, cluster_input.method)
    else:
        try:
            profiles: TypingProfileOutput = await get_typing_profiles(
                db, cluster_input.sample_ids, typing_method.value
            )
        except EntryNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error,
            ) from error
        job = schedule_allele_cluster_samples(profiles, cluster_input.method)
    return job


class IndexInput(RWModel):  # pylint: disable=too-few-public-methods
    """Input data model for index entrypoint.

    :param RWModel: Generic read write base model
    :type RWModel: Generic basemodel for read/ write
    """

    sample_ids: list[str] = Field(..., min_length=1)
    force: bool = False


@router.post("/minhash/index", status_code=status.HTTP_202_ACCEPTED, tags=["minhash"])
async def index_genome_signatures(index_input: IndexInput) -> Dict[str, str]:
    """Entrypoint for scheduling indexing of sourmash signatures.

    :raises HTTPException: Return 500 HTTP error signature path cant be generated
    :raises HTTPException: Return 404 HTTP error if no signatures were found
    :return: Indexing job id
    :rtype: Dict[str, str]
    """
    try:
        signatures = await get_signature_path_for_samples(db, index_input.sample_ids)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error
        ) from error

    # verify results
    if len(signatures) == 0:
        sids = ", ".join(index_input.sample_ids)
        msg = f"No signatures found for samples: {sids}"
        LOG.warning(msg)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=msg,
        )
    signature_paths = [Path(sig["genome_signature"]) for sig in signatures]
    job_id: str = schedule_add_genome_signature_to_index(signature_paths)
    return {"job_id": job_id}
