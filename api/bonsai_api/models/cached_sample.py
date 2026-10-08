"""Model for the bookkeeping of which samples are cached in MongoDB."""

import datetime as dt

from pydantic import BaseModel


class CachedSample(BaseModel):  # pylint: disable=too-few-public-methods
    """A sample document that is present in the sample collection.

    The sample collection only caches samples; the permanent copy is in HCP.
    """

    sample_id: str
    cached_at: dt.datetime
    last_accessed_at: dt.datetime
    last_accessed_by: str | None = None

