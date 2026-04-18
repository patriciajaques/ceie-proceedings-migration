"""Helpers for sectionAbbrev values produced from OJS / Milanesa TOC."""

from __future__ import annotations


def is_editorial_section_abbrev(section_abbrev: str | None) -> bool:
    """
    Return True if the TOC row belongs to an editorial block.

    Base abbreviation for editorials is EDT; _make_abbrev_unique may produce
    EDT-1, EDT-2, etc. when the same base repeats.
    """
    if section_abbrev is None:
        return False
    s = str(section_abbrev).strip().upper()
    if s == "EDT":
        return True
    return s.startswith("EDT-")
