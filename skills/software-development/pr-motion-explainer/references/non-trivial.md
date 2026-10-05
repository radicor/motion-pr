# What counts as a non-trivial PR

The gate is the point of this skill. An explainer for a typo fix costs a reviewer
more than it gives. The verdict lives in `scripts/pr_brief.py` (`judge()`), and
this file is the reasoning behind its thresholds.

## The rule

A change is **non-trivial** when any one of these is true:

| Trigger | Threshold | Why |
|---|---|---|
| Changed lines | >= 40 added + deleted | Below that, the diff is readable in one sitting. A video is longer than the read. Counted over **meaningful files only**, so churn in a file the gate already discarded cannot trip it on its own. |
| Meaningful files | >= 3 | One file is a patch. Three or more is a change in how a subsystem behaves. Fires at 3 files regardless of line count -- there is no separate line floor that can silently cancel it. |
| Sensitive path | any match, and >= 8 changed lines | `api`, `auth`, `oauth`, `session`, `permissions`, `security`, `billing`, `payment`, `migrations`, `schema`, `crypto`, `token`, `index`, `query`, `cache`, `queue`, `worker`, `middleware`, `router`, `entrypoint`, `main`, plus `*.sql`, `*.proto`, `*.graphql`, `*.tf`, `*.yaml`, `*.yml`. A 6-line change to an auth middleware outranks a 400-line refactor of leaf utilities. The line floor is what stops a one-line typo in `auth.py` from becoming a video. |
| Dependency change | any, and >= 8 changed lines | `package.json`, lockfiles, `requirements*.txt`, `go.mod`, `Cargo.toml`, `Gemfile`, `composer.json`. New transitive surface and new CVEs arrive through these. |

Path signals -- `*.ts` and `*.proto` as a contract change, `routes/` as a new
endpoint, `tests/`, and the rest of `SIGNALS` in `pr_brief.py` -- are **not**
triggers. They choose the words the beats use, so a `*.ts`-only diff with three
changed lines is still trivial. Only the four rows above decide.

A change is **trivial** when none of the four triggers fire. Version bumps,
generated files, and doc edits land here even when the line count is large,
because `files_ignored` holds them out of the meaningful set first -- and the
line threshold is applied after that hold-out, not before.

A **trivial** verdict names the thresholds it came up against, so the reader can
see whether to argue with the gate or to tune it. A real run prints:

    [TRIVIAL (skip the explainer)] PR None docs: expand install notes
      - too small to animate: 4 changed lines < 40; 1 meaningful file(s) < 3

The verdict keeps the two lists that produced that line separate: `triggers` is
what fired, `thresholds_missed` is what did not, and `reasons` is `triggers`
verbatim on a pass. Folding a statement like "no meaningful files" into
`triggers` once made a verdict contradict its own reason, so `tests/test_gate.py`
asserts `non_trivial == bool(triggers)` over every case rather than trusting the
comments to keep them apart.

## The judgement call

The gate is mechanical on purpose: it has to be reproducible, or nobody trusts
it. When it fires on something that does not deserve a video, the fix is to
tune the thresholds in one place (`judge()` in `scripts/pr_brief.py`), update
this file's table to match, and say so in the PR thread, not to hand-wave the
next one. `tests/test_gate.py` holds one case per threshold and carve-out, so a
change that contradicts this table fails the suite instead of shipping quietly.

Two cases where you should override, and say which you used:

- **`--force` on a trivial diff.** Sometimes the point of the PR is not the
  lines (a 3-line env flip that unblocks a deploy is a real story). Emit the
  beats anyway and keep the video to 3 scenes.
- **Skip a non-trivial PR deliberately.** A 900-line vendored bump that trips
  the line threshold, or a lockfile-only change you force past. Record the
  skip reason in the PR comment so the next reviewer does not ask.

## What the beats must contain

Beats are ordered and fixed: `problem`, `before`, `change`, `after`, `proof`,
`cost`, `recap`. The middle three are the review; `proof` names the test files
that came with the diff or states plainly that there are none; `cost` names the
revert path and, for a PR labelled breaking, the migration path.

`proof` and `cost` are the two beats that stop an explainer from being
decoration. If `proof` says "no tests in the diff", that sentence belongs in
the video, not hidden in the PR description.
