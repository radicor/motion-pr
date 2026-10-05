"""Beat construction and the prose helpers that decide what a reviewer reads.

The `problem`/`change`/`after` trio once all read the same `describe_shape()`
clause, so a reviewer saw the same sentence three times in a 30-second video.
These tests hold the beats apart and pin the plurals, the ranking that picks a
lead file, and the sentence-picking that produces the `problem` beat.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.diffs import diff, file_diff, lines

import pr_brief
from brief_schema import SCHEMA_VERSION

GOLDEN = Path(__file__).parent / "golden" / "session-revocation.json"


def build_brief(text: str, pr: dict) -> dict:
    """What pr_brief.py main() writes, without going near git or gh."""
    files = pr_brief.collect_files(text)
    verdict = pr_brief.judge(pr, text, files)
    beats = pr_brief.build_beats(pr, text, files, verdict["signals"],
                                 verdict["added"], verdict["deleted"])
    return {
        "schema": SCHEMA_VERSION,
        "source": {"pr": pr.get("number"), "url": pr.get("url"), "title": pr.get("title"),
                   "author": (pr.get("author") or {}).get("login"), "base": None,
                   "head": None, "head_sha": pr.get("head_sha"), "range": None},
        "verdict": verdict,
        "beats": beats,
        "beat_order": pr_brief.BEAT_ORDER,
    }


# A diff with a signal, a migration, and a dependency change -- one that trips
# every trigger the gate has, which is what makes it a useful golden.
CANONICAL = diff(
    file_diff("src/auth/session.py",
              added=("def revoke(user, token):", "    store.delete(token)",
                     "    audit.log(user, 'revoke')"),
              deleted=("def logout(user):",)),
    file_diff("db/migrations/004_sessions.sql",
              added=("ALTER TABLE sessions ADD COLUMN revoked_at TIMESTAMP;",)),
    file_diff("requirements.txt", added=("redis>=4.0",)),
)

CANONICAL_PR = {
    "number": 42,
    "title": "Revoke sessions server-side",
    "url": "https://github.com/demo/payments/pull/42",
    "body": ("Sessions could not be ended without a password change, so a stolen "
             "token stayed valid until it expired.\n\nFixes #7"),
    "labels": ["breaking"],
    "author": {"login": "ada"},
    "head_sha": "a" * 40,
}

# No signal path anywhere in it, which is the shape that used to make three
# beats read the same clause.
NO_SIGNAL = diff(
    file_diff("src/billing/ledger.py", lines(20)),
    file_diff("src/billing/reports.py", lines(20)),
    file_diff("src/billing/util.py", lines(20)),
)


class GoldenBrief(unittest.TestCase):
    """The canonical brief, pinned end to end.

    A golden file only earns its keep if a human read it once; this one was
    reviewed when it was committed. When it changes, diff it and decide whether
    the change is a fix or a regression before updating it.
    """

    def test_matches_golden(self) -> None:
        brief = build_brief(CANONICAL, CANONICAL_PR)
        self.assertEqual(brief, json.loads(GOLDEN.read_text()))


class BeatShape(unittest.TestCase):
    def test_order_is_fixed(self) -> None:
        beats = pr_brief.build_beats(CANONICAL_PR, CANONICAL, pr_brief.collect_files(CANONICAL),
                                     ["auth or permissions", "schema or migration"], 5, 1)
        self.assertEqual([b["name"] for b in beats], pr_brief.BEAT_ORDER)

    def test_every_beat_carries_the_renderer_contract(self) -> None:
        beats = pr_brief.build_beats(CANONICAL_PR, CANONICAL, pr_brief.collect_files(CANONICAL),
                                     ["auth or permissions"], 5, 1)
        for beat in beats:
            with self.subTest(beat=beat["name"]):
                self.assertIn("headline", beat)
                self.assertIn("detail", beat)
                self.assertIn("code_refs", beat)

    def test_no_two_beats_repeat_the_same_line(self) -> None:
        """The repetition defect: headline plus detail colliding across beats.

        The recap restating the PR title is what a recap is for, so the title is
        exempt; the defect was the problem/change/after trio all reading the
        same describe_shape() clause.
        """
        beats = pr_brief.build_beats(CANONICAL_PR, CANONICAL, pr_brief.collect_files(CANONICAL),
                                     [], 41, 0)
        exempt = {CANONICAL_PR["title"]}
        seen = set()
        for beat in beats:
            for text in (beat["headline"], beat["detail"]):
                if text in exempt:
                    continue
                self.assertNotIn(text, seen, f"{beat['name']} repeats an earlier line")
                seen.add(text)

    def test_change_and_after_differ_when_no_signal_matches(self) -> None:
        beats = pr_brief.build_beats(CANONICAL_PR, NO_SIGNAL, pr_brief.collect_files(NO_SIGNAL),
                                     [], 60, 0)
        by_name = {b["name"]: b for b in beats}
        self.assertNotEqual(by_name["change"]["headline"], by_name["after"]["detail"])
        self.assertNotIn(by_name["change"]["detail"], by_name["after"]["detail"])
        self.assertIn("read", by_name["after"]["detail"].lower())

    def test_recap_repeats_the_pr_title(self) -> None:
        beats = pr_brief.build_beats(CANONICAL_PR, CANONICAL, pr_brief.collect_files(CANONICAL),
                                     [], 41, 0)
        self.assertEqual(beats[-1]["headline"], CANONICAL_PR["title"])

    def test_proof_names_missing_tests(self) -> None:
        beats = pr_brief.build_beats(CANONICAL_PR, CANONICAL, pr_brief.collect_files(CANONICAL),
                                     [], 41, 0)
        proof = next(b for b in beats if b["name"] == "proof")
        self.assertEqual(proof["headline"], "Evidence: no tests in the diff")

    def test_cost_names_a_breaking_label(self) -> None:
        beats = pr_brief.build_beats(CANONICAL_PR, CANONICAL, pr_brief.collect_files(CANONICAL),
                                     ["schema or migration"], 41, 0)
        cost = next(b for b in beats if b["name"] == "cost")
        self.assertIn("migration path", cost["detail"])


class Plurals(unittest.TestCase):
    """`1 meaningful files.` is the defect this pins."""

    def one_file(self) -> str:
        return diff(file_diff("src/core.py", lines(45)))

    def three_files(self) -> str:
        return diff(file_diff("src/a.py", lines(20)),
                    file_diff("src/b.py", lines(20)),
                    file_diff("src/c.py", lines(20)))

    def test_singular(self) -> None:
        beats = pr_brief.build_beats({}, self.one_file(), pr_brief.collect_files(self.one_file()),
                                     [], 45, 0)
        before, after = beats[1], beats[3]
        self.assertEqual(before["headline"], "Before: 1 file")
        self.assertIn("across 1 meaningful file.", before["detail"])
        self.assertEqual(after["headline"], "After: 1 file touched")

    def test_plural(self) -> None:
        three = self.three_files()
        beats = pr_brief.build_beats({}, three, pr_brief.collect_files(three), [], 60, 0)
        self.assertEqual(beats[1]["headline"], "Before: 3 files")
        self.assertIn("across 3 meaningful files.", beats[1]["detail"])
        self.assertEqual(beats[3]["headline"], "After: 3 files touched")


class RankForLead(unittest.TestCase):
    """git emits dotfiles first, so a beat that picks files[0] leads on .gitignore."""

    def test_dotfiles_sink_below_code(self) -> None:
        ranked = pr_brief.rank_for_lead([".gitignore", ".editorconfig", "src/main.py"])
        self.assertEqual(ranked[0], "src/main.py")

    def test_tests_sink_below_code(self) -> None:
        ranked = pr_brief.rank_for_lead(["src/auth.py", "tests/auth_test.py", "tests/conftest.py"])
        self.assertEqual(ranked[0], "src/auth.py")

    def test_deeper_paths_lead_shallower_ones(self) -> None:
        ranked = pr_brief.rank_for_lead(["util.py", "src/auth/session.py"])
        self.assertEqual(ranked[0], "src/auth/session.py")

    def test_ties_break_alphabetically(self) -> None:
        ranked = pr_brief.rank_for_lead(["src/zeta.py", "src/alpha.py"])
        self.assertEqual(ranked[0], "src/alpha.py")


class DescribeChange(unittest.TestCase):
    def test_signal_leads(self) -> None:
        self.assertEqual(pr_brief.describe_change(["auth or permissions"], 10, ["src/auth.py"]),
                         "Change: auth or permissions")

    def test_no_files(self) -> None:
        self.assertEqual(pr_brief.describe_change([], 0, []), "Change: no reviewable files")

    def test_large_diff_without_a_signal(self) -> None:
        self.assertEqual(pr_brief.describe_change([], 250, ["a.py", "b.py"]),
                         "Change: spread across 2 files")

    def test_small_diff_without_a_signal(self) -> None:
        self.assertEqual(pr_brief.describe_change([], 50, ["a.py"]), "Change: focused edit")


class DescribeShapeAndFocus(unittest.TestCase):
    def test_single_file(self) -> None:
        self.assertEqual(pr_brief.describe_shape(["src/auth.py"]),
                         "everything lands in auth.py")

    def test_lead_plus_others(self) -> None:
        self.assertEqual(
            pr_brief.describe_shape(["src/billing/ledger.py", "src/billing/reports.py",
                                    "src/billing/util.py", "src/other.py"]),
            "ledger.py leads, with reports.py, util.py and other.py")

    def test_reviewer_focus_names_the_lead(self) -> None:
        self.assertEqual(pr_brief.reviewer_focus(["src/billing/ledger.py", "other.py"]),
                         "Reviewer focus: read ledger.py first")

    def test_reviewer_focus_with_nothing_to_read(self) -> None:
        self.assertEqual(pr_brief.reviewer_focus([]), "Reviewer focus: nothing meaningful to review")


class FirstProblemSentence(unittest.TestCase):
    def test_skips_the_closer_line(self) -> None:
        body = "Fixes #7\n\nSessions could not be ended without a password change."
        self.assertEqual(pr_brief.first_problem_sentence(body),
                         "Sessions could not be ended without a password change.")

    def test_skips_headings(self) -> None:
        body = "## What changed\n\nSessions could not be ended without a password change."
        self.assertEqual(pr_brief.first_problem_sentence(body),
                         "Sessions could not be ended without a password change.")

    def test_skips_what_and_why(self) -> None:
        body = "Why\n\nSessions could not be ended without a password change."
        self.assertEqual(pr_brief.first_problem_sentence(body),
                         "Sessions could not be ended without a password change.")

    def test_returns_nothing_for_an_unparseable_body(self) -> None:
        self.assertEqual(pr_brief.first_problem_sentence("ok"), "")

    def test_rejects_a_sentence_shorter_than_twenty_chars(self) -> None:
        self.assertEqual(pr_brief.first_problem_sentence("Too short to keep."), "")

    def test_accepts_the_lower_bound(self) -> None:
        self.assertEqual(pr_brief.first_problem_sentence("Exactly twenty chars."), "Exactly twenty chars.")

    def test_rejects_a_sentence_longer_than_220_chars(self) -> None:
        long = "x " * 200
        self.assertEqual(pr_brief.first_problem_sentence(long), "")

    def test_skips_table_rows(self) -> None:
        body = "| col | other |\n|---|---|\n| a | b |\n\nSessions could not be ended without a password change."
        self.assertEqual(pr_brief.first_problem_sentence(body),
                         "Sessions could not be ended without a password change.")


class DiffParsing(unittest.TestCase):
    def test_collect_files_skips_dev_null(self) -> None:
        text = diff(file_diff("src/new.py", lines(3))) + (
            "diff --git a/src/old.py b/src/old.py\ndeleted file mode 100644\n"
            "--- a/src/old.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n")
        self.assertEqual(pr_brief.collect_files(text), ["src/new.py"])

    def test_hunks_carry_the_new_side_range(self) -> None:
        text = file_diff("src/core.py", lines(3), new_start=42)
        hunks = pr_brief.hunks(text)
        self.assertEqual(len(hunks), 1)
        self.assertEqual(hunks[0]["path"], "src/core.py")
        self.assertEqual(hunks[0]["start"], 42)

    def test_added_snippets_skip_the_header_line(self) -> None:
        text = file_diff("src/core.py", ("x = 1",))
        snippets = pr_brief.added_snippets(text)
        self.assertEqual(snippets["src/core.py"], ["x = 1"])

    def test_line_counts_by_file_keys_paths_like_collect_files(self) -> None:
        text = diff(file_diff("src/a.py", lines(4), lines(2)),
                    file_diff("src/b.py", lines(1)))
        counts = pr_brief.line_counts_by_file(text)
        self.assertEqual(counts["src/a.py"], (4, 2))
        self.assertEqual(counts["src/b.py"], (1, 0))


if __name__ == "__main__":
    unittest.main()
