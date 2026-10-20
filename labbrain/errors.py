"""Errors whose messages are safe to print; the CLI reports them with exit code 2."""

from __future__ import annotations


class EngineError(Exception):
    """A refused or failed engine operation.

    The message names files, note IDs, run IDs and field names only, never file
    contents, config values or frontmatter values.
    """
