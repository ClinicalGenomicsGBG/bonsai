"""Model for the mock HCI index, a stand-in for the real HCI."""

import datetime as dt
from typing import Any

from pydantic import BaseModel


class HciMockEntry(BaseModel):  # pylint: disable=too-few-public-methods
    """A sample document that has been uploaded to HCP.

    Entries are permanent: they are not removed when the sample is evicted
    from the MongoDB cache.
    """

    sample_id: str
    hcp_bucket: str
    hcp_key: str
    registered_at: dt.datetime
    # The sample's row as shown on the groups pages, i.e. one entry of the
    # "data" list returned by crud.sample.get_samples_summary.
    summary: dict[str, Any]

