"""Whether logs may contain sample IDs and related values (file paths named after samples).

With LOG_SAMPLE_IDS=false, they are replaced by "<hidden>" in log messages.
All other logging is unaffected.
"""

import os

LOG_SAMPLE_IDS: bool = os.environ.get("LOG_SAMPLE_IDS", "true").strip().lower() not in ("0", "false", "no", "off")


def private(value):
    """The value, or "<hidden>" if sample IDs and related values must not be logged."""
    return value if LOG_SAMPLE_IDS else "<hidden>"
