"""Well-formed synthetic diffs, so gate tests need no git and no temp repo.

Every case the gate got wrong was a real diff once. Hand-pasting those blobs
works, but a fixture with a typo'd hunk header parses to nothing and the test
silently passes on an empty diff. Building diffs from parts keeps each case a
couple of readable lines and makes a malformed fixture impossible to write
without noticing.
"""

from __future__ import annotations


def file_diff(path: str, added: tuple[str, ...] = (), deleted: tuple[str, ...] = (),
              new_start: int = 1) -> str:
    """One file's worth of unified diff, new side only."""
    old_count = max(len(deleted), 1)
    new_count = max(len(added), 1)
    lines = [f"diff --git a/{path} b/{path}",
             f"--- a/{path}", f"+++ b/{path}",
             f"@@ -1,{old_count} +{new_start},{new_count} @@"]
    lines += ["-" + line for line in deleted]
    lines += ["+" + line for line in added]
    return "\n".join(lines) + "\n"


def deleted_file(path: str, body: tuple[str, ...]) -> str:
    """A file removed wholesale. The new side is /dev/null, which collect_files skips."""
    lines = "\n".join("-" + line for line in body)
    return (f"diff --git a/{path} b/{path}\n"
            f"deleted file mode 100644\n"
            f"--- a/{path}\n+++ /dev/null\n"
            f"@@ -1,{len(body)} +0,0 @@\n{lines}\n")


def diff(*file_diffs: str) -> str:
    """A multi-file diff is just file diffs concatenated."""
    return "\n".join(file_diffs)


def lines(n: int, text: str = "x = 1") -> tuple[str, ...]:
    """n identical lines -- the shape of a lockfile or a generated bump."""
    return tuple(text for _ in range(n))
