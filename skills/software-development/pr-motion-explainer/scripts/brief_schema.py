#!/usr/bin/env python3
"""The brief's contract, shared by the writer and both renderers.

`pr_brief.py` writes a brief; `render.py` and `poster.py` read it. The brief is
also meant to be hand-edited between gating and rendering (SKILL.md says so), so
it is a real interface rather than an internal struct. A missing key used to
surface as `KeyError: 'source'` halfway through a render, which tells neither an
agent nor a user what to do about it.

Bumping `SCHEMA_VERSION` is a breaking change the renderers enforce, so an old
brief fails with "re-run pr_brief.py" instead of rendering a half-formed page.
"""

from __future__ import annotations

SCHEMA_VERSION = 2

# Keys a renderer dereferences directly. Anything in these tuples that goes
# missing is a KeyError in `render.py` or `poster.py`, so it belongs to the
# schema rather than to the caller's good intentions.
TOP_LEVEL = ("source", "verdict", "beats", "beat_order", "schema")
SOURCE_REQUIRED = ("pr", "url", "title", "head_sha")
VERDICT_REQUIRED = ("changed_lines", "added", "deleted", "files_meaningful")
BEAT_REQUIRED = ("name", "headline", "detail")


def validate_brief(brief: object) -> list[str]:
    """Structural problems, as messages someone can act on. Empty list == ok.

    An empty `beats` list is deliberately not a schema problem: it is the normal
    output for a trivial PR, and the renderers report it as exit 3.
    """
    if not isinstance(brief, dict):
        return ["brief is not a JSON object"]

    problems: list[str] = []
    for key in TOP_LEVEL:
        if key not in brief:
            problems.append(f"missing the top-level key '{key}'")

    schema = brief.get("schema")
    if schema is None:
        problems.append(
            "no schema version: this brief predates schema v2 or was written by "
            "hand. Re-run pr_brief.py to regenerate it")
    elif schema != SCHEMA_VERSION:
        problems.append(
            f"schema v{schema}, this skill writes v{SCHEMA_VERSION}. "
            "Re-run pr_brief.py to regenerate it")

    src = brief.get("source")
    if isinstance(src, dict):
        for key in SOURCE_REQUIRED:
            if key not in src:
                problems.append(f"source is missing '{key}'")
    verdict = brief.get("verdict")
    if isinstance(verdict, dict):
        for key in VERDICT_REQUIRED:
            if key not in verdict:
                problems.append(f"verdict is missing '{key}'")

    beats = brief.get("beats")
    if isinstance(beats, list):
        for i, beat in enumerate(beats):
            if not isinstance(beat, dict):
                problems.append(f"beats[{i}] is not an object")
                continue
            for key in BEAT_REQUIRED:
                if key not in beat:
                    problems.append(f"beats[{i}] is missing '{key}'")
    return problems
