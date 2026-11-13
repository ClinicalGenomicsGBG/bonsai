"""Whether logs may contain sample IDs and related values.

With LOG_SAMPLE_IDS=false, sample IDs, LIMS IDs, sample names, HCP keys,
usernames and request URLs are replaced by "<hidden>" in log messages, the
API's access log is off, and queued jobs are described without their arguments
(which workers would otherwise log). All other logging is unaffected.
"""

import os

LOG_SAMPLE_IDS: bool = os.environ.get("LOG_SAMPLE_IDS", "true").strip().lower() not in ("0", "false", "no", "off")
HIDDEN = "<hidden>"


def private(value):
    """The value, or "<hidden>" if sample IDs and related values must not be logged."""
    return value if LOG_SAMPLE_IDS else HIDDEN


def job_description(task: str) -> str | None:
    """Description for a queued rq job, which its worker logs.

    None means rq's default: the call with its arguments (sample IDs, keys, ...).
    """
    return None if LOG_SAMPLE_IDS else f"{task}({HIDDEN})"
