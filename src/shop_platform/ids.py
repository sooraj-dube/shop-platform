"""Prefixed identifiers such as ``ord_4f1c9a...``."""

import re
import uuid

_PREFIX = re.compile(r"^[a-z]{2,5}$")


def new_id(prefix: str) -> str:
    """Return ``<prefix>_<32 hex chars>``. The prefix tells a reader what kind of id it is."""
    if not _PREFIX.match(prefix):
        raise ValueError(f"prefix must be 2-5 lowercase letters, got {prefix!r}")
    return f"{prefix}_{uuid.uuid4().hex}"
