"""Define redis tasks."""
import logging
import json
import os
import tempfile
import time

from botocore.config import Config
import boto3
import botocore.exceptions
from NGPIris import HCPHandler
from NGPIris.hcp.exceptions import ObjectAlreadyExistError

from dataclasses import dataclass
from string import Formatter

LOG = logging.getLogger(__name__)
if not LOG.handlers:  #rq only configures its own logger
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    LOG.addHandler(_handler)
    LOG.setLevel(logging.INFO)

FAST_FAIL = Config(
    connect_timeout=5,
    read_timeout=30,
    retries={
        "mode": "standard",
        "max_attempts": 2,
    },
)


@dataclass(frozen=True)
class Settings:
    credentials: str
    bucket: str
    key_template: str
    #use_ssl: bool # ? Note: not used in VDP, is this necessary?
    #ca_bundle: str | None # Note: not used in VDP? Is this necessary?

class DeadlineExceeded(Exception):
    """The API has stopped waiting for this upload and rolled back MongoDB."""


def load_settings() -> Settings:
    bucket = os.environ.get("HCP_BUCKET", None)
    if not bucket:
        raise RuntimeError("'HCP_BUCKET' is not set.")

    hcp_creds_path = os.environ.get("HCP_CREDS_CONTAINER", None)
    if not hcp_creds_path:
        raise RuntimeError("'HCP_CREDS_CONTAINER' is not set.")

    key_template = os.environ.get("HCP_KEY_TEMPLATE")
    if not key_template:
        raise RuntimeError("'HCP_KEY_TEMPLATE' is not set.")

    return Settings(
        credentials=hcp_creds_path,
        bucket=bucket,
        key_template=key_template,
    )


def connect(config: Settings) -> HCPHandler:
    """much connect"""
    hcp = HCPHandler(config.credentials)
    # if config.use_ssl and config.ca_bundle
    hcp.s3_client = boto3.client(
        "s3",
        aws_access_key_id=hcp.username,
        aws_secret_access_key=hcp.password,
        endpoint_url=hcp.endpoint,

        config=hcp.s3_client.meta.config.merge(FAST_FAIL),
    )
    try:
        hcp.mount_bucket(config.bucket)
    except botocore.exceptions.ConnectionError as error:
        # covers connect timeouts, unreachable endpoints, TLS and proxy errors
        # 'from None' hides the chained exceptions from urllib3 and botocore,
        #   reducing the noise in the container logs.
        raise ConnectionError(f"HCP not reachable: {error}") from None
    return hcp

def object_key(template: str, document: dict) -> str:
    """Build the object key from top-level fields of the document, e.g. {sample_id}."""
    names = {name for _, name, _, _ in Formatter().parse(template) if name}
    missing = names - document.keys()
    if missing:
        raise KeyError(f"HCP_KEY_TEMPLATE uses fields not in the document: {sorted(missing)}")
    for name in names:
        value = document[name]
        if not isinstance(value, (str, int, float)) or "/" in str(value) or "\\" in str(value):
            # a slash in e.g. sample_id would silently change the key's folder structure
            raise ValueError(f"Field {name}={value!r} can't be used in an object key")
    return template.format_map({name: document[name] for name in names})


def replace_object(hcp: HCPHandler, config: Settings, key: str, document: str, deadline: float) -> None:
    """Replace an existing object, and restore it if the API has given up meanwhile."""
    # keep the current content, so the replacement can be undone
    previous = hcp.s3_client.get_object(Bucket=config.bucket, Key=key)["Body"].read()
    # NGPIris' upload_file refuses existing objects. put_object replaces the
    # object in one request, so HCP never lacks it in between.
    hcp.s3_client.put_object(Bucket=config.bucket, Key=key, Body=document.encode("utf-8"))
    if time.time() > deadline:
        # the API has already rolled back MongoDB, so restore the replaced content as well
        hcp.s3_client.put_object(Bucket=config.bucket, Key=key, Body=previous)
        raise DeadlineExceeded(f"Replacement of {key} finished after the API deadline; previous content restored")


def upload_sample(document:str, deadline: float, overwrite: bool = False) -> dict:
    """Upload a sample document to the HCP

    :param document: The Sample document to upload.
    :param overwrite: Replace an existing object instead of skipping the upload.
    """
    if time.time() > deadline:
        raise DeadlineExceeded("Upload started after the API deadline; object not uploaded")

    config = load_settings()
    key = object_key(config.key_template, json.loads(document))
    hcp = connect(config)
    return_object_base: dict[str, str|bool] = {
        "key": key,
        "bucket": config.bucket,
    }

    if hcp.object_exists(key):
        if overwrite:
            replace_object(hcp, config, key, document, deadline)
            LOG.info("Replaced '%s' in bucket '%s'", key, config.bucket)
            return return_object_base | {"uploaded": True}
        LOG.info("Sample '%s' already exists in bucket '%s', skipping upload", key, config.bucket)
        return return_object_base | {"uploaded": False}

    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as tmp:
        tmp.write(document)

    try:
        hcp.upload_file(tmp.name, key=key, show_progress_bar=False)
    except ObjectAlreadyExistError:  # The file was uploaded after the hcp.object_exists check above
        LOG.info("%s already exists in bucket %s, skipping upload", key, config.bucket)
        return return_object_base | {"uploaded": False}
    finally:
        os.unlink(tmp.name)

    if time.time() > deadline:
        # the API has already rolled back MongoDB, so roll back the HCP upload as well
        hcp.delete_object(key)
        raise DeadlineExceeded(f"Upload of {key} finished after the API deadline; object deleted")

    LOG.info("Uploaded '%s' to bucket '%s'", key, config.bucket)
    return return_object_base | {"uploaded": True}

