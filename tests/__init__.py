"""Test suite for the pr-motion-explainer skill.

Runs on the stdlib alone, no pip and no network:

    python3 -m unittest discover -s tests -t . -v

The skill's scripts are plain modules in skills/.../scripts, not a package, so
this package puts that directory on sys.path once instead of repeating the
path surgery in every test module.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1].joinpath(
    "skills", "software-development", "pr-motion-explainer", "scripts")
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
