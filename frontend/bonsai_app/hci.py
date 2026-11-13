import json
import re

from .config import settings
from .hci_handler import BonsaiHCIHandler
from .log_privacy import LOG_SAMPLE_IDS


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


def get_hci_samples(term: str, items: int = 500):
    h = BonsaiHCIHandler(settings.hci_credentials_path)
    if LOG_SAMPLE_IDS:
        print(h.address)
        print(f"{h.address=}")
        print(f"{h.username=}")
        print(f"{h.realm=}")
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
