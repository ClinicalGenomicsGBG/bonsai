from NGPIris import HCIHandler
from requests import Response, post


class BonsaiHCIHandler(HCIHandler):
    """NGPIris 5.6.2's HCIHandler, with realm support from NGPIris commit e90092f.

    realm "HCI": token from HCI's Keycloak (client credentials).
    Anything else, including the default "LOCAL": as before.
    """

    def __init__(self, credentials: str | dict[str, str], use_ssl: bool = False) -> None:
        super().__init__(credentials, use_ssl)
        fields = self.hci if isinstance(credentials, str) else credentials
        self.realm = fields.get("realm", "LOCAL")

    def request_token(self) -> None:
        """Request a token from HCI, and store it in self.token."""
        match self.realm:
            case "HCI":
                url = f"https://keycloak.{self.address}/realms/{self.realm}/protocol/openid-connect/token"
                data = {
                    "grant_type": "client_credentials",
                    "client_id": self.username,
                    "client_secret": self.password,
                    "realm": self.realm,
                }
            case _:  # "LOCAL"
                url = f"https://{self.address}:{self.auth_port}/auth/oauth/"
                data = {
                    "grant_type": "password",
                    "username": self.username,
                    "password": self.password,
                    "scope": "*",
                    "client_secret": "hci-client",
                    "client_id": "hci-client",
                    "realm": "LOCAL",
                }
        try:
            response: Response = post(url, data=data, verify=self.use_ssl, timeout=15)
        except Exception:
            raise ConnectionError(f"The token request made at {url} failed. Please check your connection.") from None
        self.token = response.json()["access_token"]
