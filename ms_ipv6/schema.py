"""Typed schema for plan JSON files used by ms_ipv6.

These types help document and validate the structure of the generated plan
and the plan consumed during downloads.
"""

from typing import List

from typing_extensions import Literal, NotRequired, TypedDict


class PlanFile(TypedDict):
    """An entry describing a single file to download."""

    url: str
    # Path relative to the chosen local root directory
    path: str
    # Original remote path in the repo
    remote_path: str
    # Optional size in bytes (if known)
    size: NotRequired[int]
    # Optional file size in human-readable format (if known)
    size_human: NotRequired[str]
    # Optional raw CDN URL resolved via redirect (useful for IPv6-only downloads)
    raw_url: NotRequired[str]
    # Optional SHA-256 checksum for integrity verification
    sha256: NotRequired[str]


class Plan(TypedDict):
    """The overall plan schema written to/loaded from JSON."""

    repo_id: str
    repo_type: Literal["model", "dataset"]
    endpoint: str
    revision: str
    file_count: int
    files: List[PlanFile]
    created_at: str
    version: int
