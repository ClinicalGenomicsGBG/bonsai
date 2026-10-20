"""Mimer api default configuration"""

import os
import ssl
from typing import Annotated, Literal
from pathlib import Path

from pydantic import AfterValidator, Field, FilePath
from pydantic_settings import BaseSettings, SettingsConfigDict

ssl_defaults = ssl.get_default_verify_paths()


def _validate_yaml_file(path: Path | None) -> Path | None:
    """Ensure that file is readable and looks like a YAML."""
    if path is None:
         return None
    if not os.access(path, os.R_OK):
        raise ValueError(f"LIMS export config file is not readable: {path}")
    if path.suffix.lower() not in {'.yaml', '.yml'}:
        raise ValueError(f"LIMS export config must be a .yaml or .yml file: {path}")
    return path.resolve()


LimsConfigPath = Annotated[
    FilePath | None,
    AfterValidator(_validate_yaml_file)
]

LogLevel = Annotated[
    Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    BeforeValidator(str.upper),
]


class SmtpConfig(BaseSettings):
    """SMTP server configuration."""

    host: str
    port: int = 25
    timeout: int = Field(60, description="Conection timeout in seconds.")
    use_tls: bool = False
    use_ssl: bool = False


class EmailConfig(BaseSettings):

    subject_prefix: str = "[ Bonsai ]"
    sender: str = 'do-not-reply@bonsai.app'
    sender_name: str = "Bonsai"


class Settings(BaseSettings):
    """API configuration."""

    # Configure allowed origins (CORS) for development. Origins are a comma seperated list.
    # https://fastapi.tiangolo.com/tutorial/cors/
    allowed_origins: list[str] = []

    # Database connection
    # standard URI has the form:
    # mongodb://[username:password@]host1[:port1][,...hostN[:portN]][/[defaultauthdb][?options]]
    # read more: https://docs.mongodb.com/manual/reference/connection-string/
    database_name: str = "bonsai"
    db_host: str = "mongodb"
    db_port: str = "27017"
    max_connections: int = 10
    min_connections: int = 10

    # Redis connection
    redis_host: str = "redis"
    redis_port: str = "6379"

    # HCP uploader & HCI-mock DB
    hcp_upload_enabled: bool = True
    hcp_upload_timeout: int = 60
    hcp_download_timeout: int = 60  # seconds to wait for a Sample to download from HCP
    hci_mock_database_name: str = "hci_mock"
    # What POST /samples/ does when the sample_id already exists:
    # "reject" (409 conflict) or "replace" (in MongoDB, HCP and the HCI mock).
    sample_duplicate_policy: Literal["reject", "replace"] = "reject"
    sample_cache_ttl_minutes: int = 60
    cache_cleanup_interval_seconds: int = 10  # was: 6000
    # cache_cleanup_batch_size: int = 0
    # Seconds to wait for a cleanup operation to finish before
    #   automatically releasing the redis lock
    cache_cleanup_lock_ttl_seconds: int = 10
    cache_cleanup_log_level: LogLevel = "INFO"

    # Reference genome and annotations for IGV
    reference_genomes_dir: str = "/tmp/reference_genomes"
    annotations_dir: str = "/tmp/annotations"
    # authentication options
    secret_key: str = "not-so-secret"  # openssl rand -hex 32
    access_token_expire_minutes: int = 180  # expiration time for accesst token
    api_authentication: bool = True

    # email server
    smtp: SmtpConfig | None = None
    email: EmailConfig = EmailConfig()

    # LDAP login Settings
    # If LDAP is not configured it will fallback on local authentication
    ldap_search_attr: str = "mail"
    ldap_search_filter: str | None = None
    ldap_base_dn: str | None = None
    # ldap server
    ldap_host: str | None = None
    ldap_port: int = 1389
    ldap_bind_dn: str | None = None
    ldap_secret: str | None = None
    ldap_connection_timeout: int = 10
    ldap_read_only: bool = False
    ldap_valid_names: str | None = None
    ldap_private_key_password: str | None = None
    ldap_raise_exceptions: bool = False
    ldap_user_login_attr: str = "mail"
    force_attribute_value_as_list: bool = False
    # ldap tls
    ldap_use_ssl: bool = False
    ldap_use_tls: bool = True
    ldap_tls_version: int = ssl.PROTOCOL_TLSv1
    ldap_require_cert: int = ssl.CERT_REQUIRED
    ldap_client_private_key: str | None = None
    ldap_client_cert: str | None = None
    # ldap ssl
    ldap_ca_certs_file: str | None = ssl_defaults.cafile
    ldap_ca_certs_path: str | None = ssl_defaults.capath
    ldap_ca_certs_data: str | None = None

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    lims_export_config: LimsConfigPath = Field(
        default=None,
        description=(
            "Path to custom LIMS exporter YAML configuration."
            "If omitted, the application will fall back the packaged default."
        ),
        examples=["/etc/bonsai/lims.yaml"]
        )

    @property
    def use_ldap_auth(self) -> bool:
        """Return True if LDAP authentication is enabled.

        :return: Return True if LDAP authentication is enabled
        :rtype: bool
        """
        return self.ldap_host is not None

    @property
    def mongodb_uri(self) -> str | None:
        """Create mongodb connection string."""

        return f"mongodb://{self.db_host}:{self.db_port}/{self.database_name}"


# to get a string like this run:
# openssl rand -hex 32
ALGORITHM = "HS256"

# Definition of user roles
USER_ROLES = {
    "admin": [
        "users:me",
        "users:read",
        "users:write",
        "groups:read",
        "groups:write",
        "samples:read",
        "samples:write",
        "samples:update",
        "locations:read",
        "locations:write",
    ],
    "user": [
        "users:me",
        "samples:read",
        "samples:update",
        "groups:read",
        "locations:read",
        "locations:write",
    ],
    "uploader": [
        "users:me",
        "groups:write",
        "samples:write",
    ],
}

settings = Settings()
