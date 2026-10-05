"""Golden-file coverage for the gate: `judge()` and `classify_files()`.

The gate is the product, it has been rewritten several times, and before this
suite nothing in the repo enforced its rules -- they lived in comments someone
had to remember. Each case below is either a verdict the gate once got wrong or
an intentional carve-out that a well-meaning refactor would silently undo.

`judge()` ignores its `pr` argument entirely, so the whole gate is a pure
function of the diff text and these tests need no git, no gh, and no network.
"""

from __future__ import annotations

import unittest

from tests.diffs import deleted_file, diff, file_diff, lines

import pr_brief


def judge_diff(text: str, pr: dict | None = None) -> dict:
    return pr_brief.judge(pr or {}, text, pr_brief.collect_files(text))


# (name, diff, expected verdict) -- the third column is what the gate owes.
CASES: list[tuple[str, str, bool]] = [
    # docs are held out before counting, so a docs-only diff is trivial no
    # matter how many lines it touches
    ("docs_only", diff(file_diff("docs/guide.md", lines(50))), False),
    ("nested_docs_only", diff(file_diff("apps/web/docs/api.md", lines(50))), False),
    # lockfile churn is ignored outright: a 900-line bump is not a story
    ("lockfile_only", diff(file_diff("package-lock.json", lines(900))), False),
    # vendor trees and dotfile config never reach the file count
    ("vendor_only", diff(file_diff("vendor/lib/huge.js", lines(500))), False),
    ("gitignore_only", diff(file_diff(".gitignore", lines(3))), False),
    # a whole file deleted still has no new-side path, so the gate cannot see
    # it -- recorded here as current behaviour, not as settled design
    ("deleted_file_only", diff(deleted_file("src/legacy.py", lines(50))), False),

    # sensitive paths and dependency files still need line mass behind them
    ("auth_typo", diff(file_diff("src/auth.py", ("token = new",), ("token = old",))), False),
    ("auth_with_mass", diff(file_diff("src/auth.py", lines(8))), True),
    ("manifest_version_bump", diff(
        file_diff("package.json", ('  "version": "1.2.1",',),
                  ('  "version": "1.2.0",',)),
        file_diff("package-lock.json", lines(900))), False),
    ("dependency_with_mass", diff(
        file_diff("package.json", lines(12)),
        file_diff("package-lock.json", lines(900))), True),
    ("requirements_tiny", diff(file_diff("requirements.txt", lines(2))), False),
    # requirements*.txt ends in .txt, which DOC_ONLY would swallow; the carve-out
    # is what makes the dependency gate work for a Python project at all
    ("requirements_with_mass", diff(file_diff("requirements.txt", lines(10))), True),

    # the file-count trigger has no line floor: it fires at 3 files regardless
    ("three_files_few_lines", diff(
        file_diff("src/a.py", lines(2)), file_diff("src/b.py", lines(2)),
        file_diff("src/c.py", lines(2))), True),
    ("two_files_35_lines", diff(
        file_diff("src/a.py", lines(20)), file_diff("src/b.py", lines(15))), False),
    ("one_file_over_threshold", diff(file_diff("src/core.py", lines(40))), True),

    # docs lines never count toward the threshold, so docs can pad a small code
    # change into an explainer -- this used to animate on lockfile mass
    ("docs_mask_small_code_change", diff(
        file_diff("docs/guide.md", lines(60)),
        file_diff("src/billing.py", lines(5))), False),
    ("docs_plus_real_code_change", diff(
        file_diff("docs/guide.md", lines(60)),
        file_diff("src/billing.py", lines(10))), True),

    # *.md is documentation by default; these are the carve-outs that keep the
    # substance of a skill or docs PR reviewable
    ("skill_manifest", diff(file_diff("SKILL.md", lines(45))), True),
    ("readme_is_meaningful", diff(file_diff("README.md", lines(45))), True),

    # sensitive by extension
    ("github_workflow", diff(file_diff(".github/workflows/ci.yml", lines(20))), True),
    ("migration_sql", diff(file_diff("db/migrations/003_users.sql", lines(10))), True),
    # a contract file is a signal, not a trigger: three lines of types is trivial
    ("contract_file_only", diff(file_diff("src/types/api.ts", lines(3))), False),
]


class VerdictTable(unittest.TestCase):
    """Every case in the table lands on its expected verdict."""

    def test_table(self) -> None:
        for name, text, expected in CASES:
            with self.subTest(case=name):
                verdict = judge_diff(text)
                self.assertEqual(verdict["non_trivial"], expected, name)

    def test_files_seen_by_the_gate_are_seen_once(self) -> None:
        for name, text, _ in CASES:
            with self.subTest(case=name):
                verdict = judge_diff(text)
                seen = verdict["files_meaningful"] + verdict["files_ignored"]
                self.assertEqual(sorted(seen), sorted(pr_brief.collect_files(text)), name)

    def test_non_trivial_iff_a_trigger_fired(self) -> None:
        """`triggers` and `thresholds_missed` are separate lists and must stay that way.

        A verdict is non-trivial exactly when something fired, and `reasons` is
        then the trigger list verbatim. Folding a statement like "no meaningful
        files" into triggers once made a verdict contradict its own reason, so
        the two lists are kept distinct and the separation is asserted here.
        """
        for name, text, non_trivial in CASES:
            with self.subTest(case=name):
                verdict = judge_diff(text)
                self.assertEqual(verdict["non_trivial"], bool(verdict["triggers"]), name)
                if non_trivial:
                    self.assertEqual(verdict["reasons"], verdict["triggers"], name)
                else:
                    self.assertTrue(verdict["reasons"], "a trivial verdict must say why")

    def test_trivial_verdict_reports_no_trigger_as_fired(self) -> None:
        for name, text, non_trivial in CASES:
            if non_trivial:
                continue
            with self.subTest(case=name):
                verdict = judge_diff(text)
                self.assertEqual(verdict["triggers"], [], name)


class CountedLines(unittest.TestCase):
    """Only lines in files the gate kept count."""

    def test_lockfile_lines_do_not_count(self) -> None:
        verdict = judge_diff(diff(
            file_diff("package-lock.json", lines(900)),
            file_diff("package.json", lines(10))))
        self.assertEqual(verdict["changed_lines"], 10)

    def test_docs_lines_do_not_count(self) -> None:
        verdict = judge_diff(diff(
            file_diff("docs/guide.md", lines(60)),
            file_diff("src/billing.py", lines(10))))
        self.assertEqual(verdict["changed_lines"], 10)
        self.assertEqual(verdict["added"], 10)
        self.assertEqual(verdict["deleted"], 0)

    def test_line_counts_skip_diff_headers(self) -> None:
        """The +++/---/diff lines must not be counted as added or removed."""
        verdict = judge_diff(diff(file_diff("src/core.py", lines(5))))
        self.assertEqual(verdict["added"], 5)
        self.assertEqual(verdict["deleted"], 0)


class TrivialReasons(unittest.TestCase):
    """A trivial verdict names the threshold, not a bare 'too small'."""

    def test_no_meaningful_files_names_that(self) -> None:
        verdict = judge_diff(diff(file_diff("docs/guide.md", lines(50))))
        self.assertEqual(verdict["reasons"],
                         ["no meaningful files (docs/lockfile/vendor only)"])

    def test_small_diff_lists_every_missed_threshold(self) -> None:
        verdict = judge_diff(diff(
            file_diff("src/a.py", lines(20)), file_diff("src/b.py", lines(15))))
        self.assertEqual(verdict["reasons"],
                         ["too small to animate: 35 changed lines < 40; "
                          "2 meaningful file(s) < 3"])

    def test_sensitive_without_mass_names_the_line_floor(self) -> None:
        verdict = judge_diff(diff(file_diff("src/auth.py", ("token = new",), ("token = old",))))
        self.assertEqual(verdict["reasons"],
                         ["too small to animate: 2 changed lines < 40; "
                          "1 meaningful file(s) < 3; sensitive path src/auth.py but "
                          "only 2 changed lines < 8"])

    def test_non_trivial_reports_the_trigger_that_fired(self) -> None:
        verdict = judge_diff(diff(file_diff("src/auth.py", lines(8))))
        self.assertIn("touches a sensitive path: src/auth.py", verdict["reasons"])

    def test_dependency_trigger_names_the_file_not_its_directory(self) -> None:
        verdict = judge_diff(diff(file_diff("requirements.txt", lines(10))))
        self.assertIn("dependency change: requirements.txt", verdict["reasons"])
        verdict = judge_diff(diff(file_diff("package.json", lines(12))))
        self.assertIn("dependency change: package.json", verdict["reasons"])
        # a nested dependency file names itself; the directory it lives in is
        # not the dependency
        verdict = judge_diff(diff(file_diff("web/package.json", lines(12))))
        self.assertIn("dependency change: package.json", verdict["reasons"])

    def test_file_count_trigger_has_no_line_floor(self) -> None:
        """The case that was silently cancelled by a line floor inside judge()."""
        verdict = judge_diff(diff(
            file_diff("src/a.py", lines(2)), file_diff("src/b.py", lines(2)),
            file_diff("src/c.py", lines(2))))
        self.assertTrue(verdict["non_trivial"])
        self.assertEqual(verdict["reasons"], ["3 files >= 3"])
        self.assertIn("6 changed lines < 40", verdict["thresholds_missed"])


class ClassifyFiles(unittest.TestCase):
    """The carve-outs, in the order judge() applies them."""

    def test_lockfile_is_ignored_but_manifest_is_not(self) -> None:
        meaningful, ignorable, _ = pr_brief.classify_files(
            ["package-lock.json", "package.json", "poetry.lock"])
        self.assertEqual(meaningful, ["package.json"])
        self.assertEqual(sorted(ignorable), ["package-lock.json", "poetry.lock"])

    def test_requirements_is_carved_out_of_docs(self) -> None:
        meaningful, _, _ = pr_brief.classify_files(
            ["docs/guide.md", "requirements.txt", "requirements-dev.txt"])
        self.assertEqual(meaningful, ["requirements.txt", "requirements-dev.txt"])

    def test_skill_and_readme_manifests_are_meaningful(self) -> None:
        meaningful, _, _ = pr_brief.classify_files(
            ["SKILL.md", "README.md", "AGENTS.md", "docs/guide.md"])
        self.assertEqual(meaningful, ["SKILL.md", "README.md", "AGENTS.md"])

    def test_vendor_and_dotfiles_are_ignored(self) -> None:
        _, ignorable, _ = pr_brief.classify_files(
            [".gitignore", "vendor/lib/x.js", "node_modules/pkg/index.js", "src/main.py"])
        self.assertEqual(sorted(ignorable),
                         [".gitignore", "node_modules/pkg/index.js", "vendor/lib/x.js"])

    def test_signals_follow_file_order_then_dedupe(self) -> None:
        _, _, signals = pr_brief.classify_files(
            ["src/routes/orders.ts", "db/schema.sql", "src/routes/users.ts"])
        self.assertEqual(signals, ["new endpoint", "schema or migration"])

    def test_deleted_file_path_is_collected_as_nothing(self) -> None:
        self.assertEqual(pr_brief.collect_files(deleted_file("src/x.py", lines(3))), [])


if __name__ == "__main__":
    unittest.main()
