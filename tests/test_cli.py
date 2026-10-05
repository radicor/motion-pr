"""The CLI surface: subprocess hardening, --pr auto, --offline, the publish
bundle, and the brief schema check.

Everything here runs the scripts the way a user would (as a subprocess) except
the one case where that would mean a real network call, which is mocked
instead. No test touches git, gh, or the network.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_beats import build_brief, CANONICAL, CANONICAL_PR

import pr_brief
from brief_schema import SCHEMA_VERSION, validate_brief

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "software-development" / "pr-motion-explainer" / "scripts"
GOLDEN = Path(__file__).parent / "golden" / "session-revocation.json"


def run_cli(script: str, *args: str) -> subprocess.CompletedProcess:
    """Run one of the skill's scripts the way the docs tell a user to."""
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True, cwd=ROOT)


class RunHelper(unittest.TestCase):
    """A hanging git or gh call used to take the whole session with it."""

    def test_a_slow_command_is_killed_and_reported(self) -> None:
        rc, out, err = pr_brief.run(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3)
        self.assertEqual(rc, 124)
        self.assertIn("timed out after 0.3s", err)
        self.assertIn("time.sleep", err)

    def test_a_fast_command_still_returns_its_output(self) -> None:
        rc, out, err = pr_brief.run([sys.executable, "-c", "print('hi')"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "hi")

    def test_pagers_and_prompts_are_opted_out(self) -> None:
        """A pager waits for a keypress; a credential prompt waits for a person."""
        rc, out, err = pr_brief.run(
            [sys.executable, "-c",
             "import os; print(os.environ['GIT_PAGER'], os.environ['GH_PAGER'], "
             "os.environ['GIT_TERMINAL_PROMPT'])"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.split(), ["cat", "cat", "0"])

    def test_offline_mode_uses_the_tighter_timeout(self) -> None:
        with mock.patch.object(pr_brief, "OFFLINE", True), \
                mock.patch.object(pr_brief, "OFFLINE_TIMEOUT", 0.3):
            rc, out, err = pr_brief.run([sys.executable, "-c", "import time; time.sleep(30)"])
        self.assertEqual(rc, 124)
        self.assertIn("timed out after 0.3s", err)


class OfflineMode(unittest.TestCase):
    def test_offline_with_pr_is_a_usage_error(self) -> None:
        result = run_cli("pr_brief.py", "--pr", "123", "--offline")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--offline", result.stderr)

    def test_offline_accepts_a_range(self) -> None:
        # The combination is valid, so it gets as far as running git; whatever
        # git finds is a fetch result, never a usage error.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "brief.json"
            result = run_cli("pr_brief.py", "--range", "HEAD~1..HEAD", "--offline",
                             "--out", str(out))
            self.assertNotEqual(result.returncode, 2)
            self.assertNotIn("--offline needs --range", result.stderr)


class PrAuto(unittest.TestCase):
    """`--pr auto` should remove the trip to the browser for the PR number."""

    def test_resolves_the_current_branch_pr_number(self) -> None:
        calls = []

        def fake_run(cmd, cwd=None, timeout=None):
            calls.append(cmd)
            return 0, json.dumps({"number": 42}), ""

        with mock.patch.object(pr_brief, "run", side_effect=fake_run):
            self.assertEqual(pr_brief.resolve_pr_number(None), "42")
        self.assertEqual(calls[0], ["gh", "pr", "view", "--json", "number"])

    def test_passes_repo_through(self) -> None:
        seen = {}

        def fake_run(cmd, cwd=None, timeout=None):
            seen["cmd"] = cmd
            return 0, json.dumps({"number": 7}), ""

        with mock.patch.object(pr_brief, "run", side_effect=fake_run):
            self.assertEqual(pr_brief.resolve_pr_number("owner/name"), "7")
        self.assertEqual(seen["cmd"],
                         ["gh", "pr", "view", "--json", "number", "--repo", "owner/name"])

    def test_a_branch_without_a_pr_reports_and_exits(self) -> None:
        """A failure must say so, not pass None downstream."""
        with mock.patch.object(pr_brief, "run",
                               return_value=(1, "", "no pull requests found")):
            with self.assertRaises(SystemExit) as ctx:
                pr_brief.resolve_pr_number(None)
        self.assertEqual(ctx.exception.code, 1)


class BriefSchema(unittest.TestCase):
    def test_a_freshly_built_brief_validates(self) -> None:
        brief = build_brief(CANONICAL, CANONICAL_PR)
        self.assertEqual(validate_brief(brief), [])

    def test_an_unversioned_brief_is_reported(self) -> None:
        brief = build_brief(CANONICAL, CANONICAL_PR)
        del brief["schema"]
        problems = validate_brief(brief)
        self.assertTrue(any("no schema version" in p for p in problems), problems)

    def test_an_old_schema_is_reported_with_the_versions_named(self) -> None:
        brief = build_brief(CANONICAL, CANONICAL_PR)
        brief["schema"] = 1
        problems = validate_brief(brief)
        self.assertTrue(any("schema v1" in p and f"v{SCHEMA_VERSION}" in p
                            for p in problems), problems)

    def test_a_missing_top_level_key_is_named(self) -> None:
        brief = build_brief(CANONICAL, CANONICAL_PR)
        del brief["source"]
        self.assertIn("missing the top-level key 'source'", validate_brief(brief))

    def test_a_beat_missing_a_field_is_named_by_index(self) -> None:
        brief = build_brief(CANONICAL, CANONICAL_PR)
        del brief["beats"][2]["headline"]
        self.assertIn("beats[2] is missing 'headline'", validate_brief(brief))

    def test_empty_beats_is_not_a_schema_problem(self) -> None:
        """An empty beats list is the normal trivial-PR output, reported as exit 3."""
        brief = build_brief(CANONICAL, CANONICAL_PR)
        brief["beats"] = []
        self.assertEqual(validate_brief(brief), [])

    def test_not_even_an_object(self) -> None:
        self.assertEqual(validate_brief(["not", "a", "brief"]),
                         ["brief is not a JSON object"])


class RenderCli(unittest.TestCase):
    def test_renders_the_animated_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pr.html"
            result = run_cli("render.py", str(GOLDEN), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(out.read_text().startswith("<!doctype html>"))
            self.assertIn("31s timeline", result.stderr)

    def test_static_build_injects_the_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pr.static.html"
            result = run_cli("render.py", str(GOLDEN), "--out", str(out), "--static")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('<body class="static">', out.read_text())

    def test_mermaid_snippet_is_a_fenced_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "comment.md"
            result = run_cli("render.py", str(GOLDEN), "--out", str(out), "--mermaid")
            self.assertEqual(result.returncode, 0, result.stderr)
            text = out.read_text()
            # the byline and stats lead, then the fenced diagram
            self.assertTrue(text.startswith("**"), text[:60])
            self.assertIn("```mermaid", text)
            self.assertIn("flowchart LR", text)

    def test_a_brief_with_no_beats_exits_three(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "empty.json"
            empty = build_brief(CANONICAL, CANONICAL_PR)
            empty["beats"] = []
            brief.write_text(json.dumps(empty))
            result = run_cli("render.py", str(brief), "--out", str(Path(tmp) / "x.html"))
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn("no beats", result.stderr)

    def test_a_hand_edited_brief_reports_the_schema_not_a_keyerror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.json"
            text = json.loads(GOLDEN.read_text())
            del text["source"]
            broken.write_text(json.dumps(text))
            result = run_cli("render.py", str(broken), "--out", str(Path(tmp) / "x.html"))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("not a v2 brief", result.stderr)
            self.assertIn("source", result.stderr)


class StalenessCheck(unittest.TestCase):
    """A brief whose diff has moved on describes the wrong change."""

    def test_a_matching_sha_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pr.html"
            result = run_cli("render.py", str(GOLDEN), "--out", str(out),
                             "--sha", "a" * 40)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(out.exists())

    def test_a_moved_sha_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pr.html"
            result = run_cli("render.py", str(GOLDEN), "--out", str(out),
                             "--sha", "b" * 40)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("has moved on", result.stderr)
            self.assertFalse(out.exists())

    def test_a_brief_with_no_head_sha_cannot_be_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "nosha.json"
            text = json.loads(GOLDEN.read_text())
            text["source"]["head_sha"] = None
            brief.write_text(json.dumps(text))
            result = run_cli("render.py", str(brief), "--out", str(Path(tmp) / "x.html"),
                             "--sha", "b" * 40)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("no head_sha", result.stderr)


class GithubBundle(unittest.TestCase):
    """One command emits everything the publish recipe asks for."""

    def test_writes_html_png_and_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            result = run_cli("render.py", str(GOLDEN), "--github", "--out", str(out),
                             "--sha", "a" * 40)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(p.name for p in out.iterdir()), [
                "pr-42-comment.md",
                "pr-42-contact-sheet.png",
                "pr-42-revoke-sessions-server-side.html",
            ])

    def test_the_comment_pins_the_sha_and_carries_the_diagram(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            run_cli("render.py", str(GOLDEN), "--github", "--out", str(out),
                    "--sha", "a" * 40)
            comment = (out / "pr-42-comment.md").read_text()
            pin = "https://raw.githubusercontent.com/demo/payments/" + "a" * 40
            self.assertIn(f"{pin}/pr-42-contact-sheet.png)", comment)
            self.assertIn(f"{pin}/pr-42-revoke-sessions-server-side.html)", comment)
            self.assertIn("```mermaid", comment)
            self.assertIn("flowchart LR", comment)

    def test_no_sha_leaves_placeholders_and_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            result = run_cli("render.py", str(GOLDEN), "--github", "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            comment = (out / "pr-42-comment.md").read_text()
            self.assertIn("<sha>", comment)
            self.assertIn("placeholders", result.stderr)

    def test_a_stale_sha_produces_no_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "docs"
            result = run_cli("render.py", str(GOLDEN), "--github", "--out", str(out),
                             "--sha", "b" * 40)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(out.exists())

    def test_a_range_brief_names_after_the_sha_not_a_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            brief = Path(tmp) / "range.json"
            text = json.loads(GOLDEN.read_text())
            text["source"]["pr"] = None
            text["source"]["url"] = None
            text["source"]["head_sha"] = "c0ffee" * 6 + "1234"
            brief.write_text(json.dumps(text))
            out = Path(tmp) / "docs"
            result = run_cli("render.py", str(brief), "--github", "--out", str(out),
                             "--sha", "c0ffee" * 6 + "1234")
            self.assertEqual(result.returncode, 0, result.stderr)
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual(names, [
                "pr-c0ffeec0-comment.md",
                "pr-c0ffeec0-contact-sheet.png",
                "pr-c0ffeec0-revoke-sessions-server-side.html",
            ])
            comment = (out / "pr-c0ffeec0-comment.md").read_text()
            self.assertIn("<owner>/<repo>", comment)


class PosterCli(unittest.TestCase):
    def test_writes_a_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sheet.png"
            result = run_cli("poster.py", str(GOLDEN), "--out", str(out))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(out.read_bytes()[:8],
                             b"\x89PNG\r\n\x1a\n")

    def test_a_broken_brief_reports_the_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.json"
            text = json.loads(GOLDEN.read_text())
            del text["beats"][0]["detail"]
            broken.write_text(json.dumps(text))
            result = run_cli("poster.py", str(broken), "--out", str(Path(tmp) / "x.png"))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
