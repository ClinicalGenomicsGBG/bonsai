import json
import re

from NGPIris import HCIHandler

from .config import settings


SEARCH_FIELDS = ["rootSample_name", "rootLims_id", "sequencingRun_id", "pipelineAssay"]
PIECES = re.compile(r"\w+")  # letters, digits and _: what these fields keep together


def field_query(field: str, term: str) -> str | None:
    """field:(*first AND middle AND last*), matching values that contain the term's pieces."""
    pieces = [p.lower() for p in PIECES.findall(term)]
    if not pieces:
        return None
    pieces[0] = "*" + pieces[0]
    pieces[-1] = pieces[-1] + "*"
    return f"{field}:({' AND '.join(pieces)})"


def search_query(term: str, fields: list[str] = SEARCH_FIELDS) -> str:
    return " OR ".join(q for f in fields if (q := field_query(f, term)))


def contains(result: dict, term: str, fields: list[str] = SEARCH_FIELDS) -> bool:
    """True if one of the searched fields really contains the term (ignoring case)."""
    t = term.strip().lower()
    metadata = result.get("metadata", {})
    #return any(v.lower().startswith(t) for f in fields for v in metadata.get(f, []))
    return any(t in v.lower() for f in fields for v in metadata.get(f, []))


# def get_hci_token():
#     pass
#
#
# def request_token(self) -> str:
#     """
#     Request a token from the HCI. The token is used for every operation
#     that needs to send a request to HCI.
#
#     :raises ConnectionError:
#         If there was a problem when requesting a token
#     """
#     url = "https://" + self.address + ":" + self.auth_port + "/auth/oauth/"
#
#     host = "keycloak.ngpi01.vgregion.se"
#     realm = "HCI"
#     url = f"https://${host}/realms/{realm}/protocol/openid-connect/token"
#     data = {
#         "grant_type": "client_credentials",
#         "username": self.username,
#         "password": self.password,
#         "scope": "*",
#         "client_secret": "hci-client",
#         "client_id": "hci-client",
#         "realm": "LOCAL",
#     }
#     try:
#         response: Response = post(
#             url, data=data, verify=self.use_ssl, timeout=15
#         )
#     except:  # noqa: E722  # pragma: no cover
#         error_msg: str = (
#             "The token request made at "
#             + url
#             + " failed. Please check your connection."
#         )
#         raise ConnectionError(error_msg) from None
#
#     token: str = response.json()["access_token"]
#     return token
#


def get_hci_samples(term: str, items: int = 500):
    h = HCIHandler(settings.hci_credentials_path)
    #get_token
    h.request_token()
    #resp = h.raw_query(
    #    {
    #        "indexName" : "bonsai_index_1",
    #        "queryString" : f"{search_term}",
    #        "itemsToReturn" : 1000
    #    }
    #)
    query={"indexName": "bonsai_index_1", "queryString": search_query(term), "itemsToReturn": items}
    resp = h.raw_query(query)
    if resp.get("hitCount", 0) > len(resp.get("results", [])):
        resp = h.raw_query(query | {"itemsToReturn": resp["hitCount"]})
    resp["results"] = [r for r in resp.get("results", []) if contains(r, term)]
    resp["hitCount"] = len(resp["results"])
    return resp
