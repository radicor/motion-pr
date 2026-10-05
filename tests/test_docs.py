"""The gate's documented vocabulary against the regexes that actually enforce it.

The README and `references/non-trivial.md` have both drifted from `judge()` in
opposite directions: a removed line floor stayed documented long after the code
dropped it, and the sensitive-path list stopped matching `SENSITIVE_PATH`. A
gate the docs describe differently from how it behaves is worse than an
undocumented one, because the reader tunes against the prose and the code does
something else.

The contract here is deliberately a set in this file rather than parsed out of
the regex source: adding a path to the regex should mean a visible, reviewed
change here, not a silent re-derivation.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import pr_brief

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
NON_TRIVIAL = (ROOT / "skills" / "software-development" / "pr-motion-explainer"
               / "references" / "non-trivial.md")

SENSITIVE_WORDS = {
    "api", "auth", "oauth", "session", "permissions", "security", "billing",
    "payment", "migrations", "schema", "crypto", "token", "index", "query",
    "cache", "queue", "worker", "middleware", "router", "entrypoint", "main",
}
SENSITIVE_EXTENSIONS = {"sql", "proto", "graphql", "tf", "yaml", "yml"}

DEPENDENCY_WORDS = {
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "requirements.txt", "requirements-dev.txt", "poetry.lock", "go.mod", "go.sum",
    "Cargo.toml", "Cargo.lock", "Gemfile", "Gemfile.lock", "composer.json",
    "composer.lock",
}


def backticked(line: str) -> list[str]:
    return re.findall(r"`([^`]+)`", line)


def line_with(needle: str, path: Path) -> str:
    for line in path.read_text().splitlines():
        if needle in line:
            return line
    raise AssertionError(f"{path} no longer documents {needle!r}")


class SensitivePathDocs(unittest.TestCase):
    def test_every_documented_path_matches_the_regex(self) -> None:
        for word in sorted(SENSITIVE_WORDS):
            with self.subTest(word=word):
                self.assertTrue(pr_brief.SENSITIVE_PATH.search(f"src/{word}/x.py"), word)
                self.assertTrue(pr_brief.SENSITIVE_PATH.search(f"{word}.py"), word)

    def test_every_documented_extension_matches_the_regex(self) -> None:
        for ext in sorted(SENSITIVE_EXTENSIONS):
            with self.subTest(ext=ext):
                self.assertTrue(pr_brief.SENSITIVE_PATH.search(f"db/thing.{ext}"), ext)

    def test_an_undocumented_path_does_not_match(self) -> None:
        """Guards the other direction: the regex must not be broader than the docs."""
        for path in ("src/helpers/util.py", "src/typing.py", "README.md", "a/b/c/d.py"):
            with self.subTest(path=path):
                self.assertFalse(pr_brief.SENSITIVE_PATH.search(path), path)

    def test_readme_lists_exactly_the_sensitive_vocabulary(self) -> None:
        line = line_with("a sensitive path", README)
        words = {w for w in backticked(line) if w.isalpha()}
        self.assertEqual(words, SENSITIVE_WORDS,
                         "the README's gate list and SENSITIVE_PATH disagree")

    def test_non_trivial_lists_exactly_the_sensitive_vocabulary(self) -> None:
        line = line_with("Sensitive path", NON_TRIVIAL)
        words = {w for w in backticked(line) if w.isalpha()}
        self.assertEqual(words, SENSITIVE_WORDS,
                         "non-trivial.md and SENSITIVE_PATH disagree")

    def test_the_removed_line_floor_is_not_stated_as_a_rule(self) -> None:
        """`changed < 5` was a bug that cancelled the file-count trigger.

        History prose may mention it; the rule sentence may not. The check looks
        at statements of the rule rather than at every mention, because the
        README's defect list legitimately quotes the phrase it killed.
        """
        for path in (README, NON_TRIVIAL):
            with self.subTest(doc=path.name):
                for line in path.read_text().splitlines():
                    if "trivial when" in line or "trivial if" in line:
                        self.assertNotIn("5 changed lines", line, line)

    def test_readme_lists_exactly_the_four_triggers(self) -> None:
        """`judge()` has four triggers; a fifth bullet would be a gate the code lacks."""
        text = README.read_text()
        start = text.index("A PR gets an explainer only if it trips one of these:")
        window = text[start:start + 800]
        bullets = [line for line in window.splitlines() if line.startswith("- ")]
        self.assertEqual(len(bullets), 4, window)

    def test_non_trivial_lists_exactly_the_four_triggers(self) -> None:
        text = NON_TRIVIAL.read_text()
        head = text.index("| Trigger |")
        block = text[head:text.index("\n\n", head)]
        # `startswith("| ")` skips the `|---|---|` separator, [1:] the header row
        rows = [line for line in block.splitlines() if line.startswith("| ")][1:]
        self.assertEqual(len(rows), 4, block)


class DependencyDocs(unittest.TestCase):
    def test_every_documented_dependency_file_matches_the_regex(self) -> None:
        for name in sorted(DEPENDENCY_WORDS):
            with self.subTest(name=name):
                self.assertTrue(pr_brief.DEPENDENCY_FILE.search(name), name)

    def test_an_undocumented_dependency_does_not_match(self) -> None:
        for path in ("src/deps.py", "package.json.bak", "not-requirements.txt"):
            with self.subTest(path=path):
                self.assertFalse(pr_brief.DEPENDENCY_FILE.search(path), path)

    def test_dependency_files_are_not_swallowed_as_docs(self) -> None:
        """The DOC_ONLY .txt rule has to carve requirements files back out."""
        for name in ("requirements.txt", "requirements-dev.txt"):
            with self.subTest(name=name):
                meaningful, _, _ = pr_brief.classify_files([name])
                self.assertEqual(meaningful, [name])


class ThresholdDocs(unittest.TestCase):
    """The numbers the prose quotes are the numbers the code uses."""

    def test_readme_quotes_the_real_thresholds(self) -> None:
        text = README.read_text()
        self.assertIn(f"{pr_brief.MIN_CHANGED_LINES} or more changed lines", text)
        self.assertIn(f"{pr_brief.MIN_FILES} or more meaningful files", text)
        self.assertIn(f"{pr_brief.MIN_LINES_FOR_SENSITIVE} or more changed lines", text)

    def test_non_trivial_quotes_the_real_thresholds(self) -> None:
        text = NON_TRIVIAL.read_text()
        self.assertIn(f">= {pr_brief.MIN_CHANGED_LINES} added + deleted", text)
        self.assertIn(f">= {pr_brief.MIN_FILES}", text)
        self.assertIn(f">= {pr_brief.MIN_LINES_FOR_SENSITIVE} changed lines", text)


if __name__ == "__main__":
    unittest.main()
