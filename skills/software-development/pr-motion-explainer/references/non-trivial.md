# What counts as a non-trivial PR

The gate is the point of this skill. An explainer for a typo fix costs a reviewer
more than it gives. The verdict lives in `scripts/pr_brief.py` (`judge()`), and
this file is the reasoning behind its thresholds.

## The rule

A change is **non-trivial** when any one of these is true:

| Trigger | Threshold | Why |
|---|---|---|
| Changed lines | >= 40 added + deleted | Below that, the diff is readable in one sitting. A video is longer than the read. |
| Meaningful files | >= 3 | One file is a patch. Three or more is a change in how a subsystem behaves. |
| Sensitive path | any match | `auth`, `session`, `permission`, `billing`, `payment`, `migrations`, `schema`, `crypto`, `token`, `index`, `cache`, `queue`, `worker`, `middleware`, `router`, `entrypoint`, plus `*.sql`, `*.proto`, `*.graphql`, `*.tf`, IaC YAML. A 6-line change to an auth middleware outranks a 400-line refactor of leaf utilities. |
| Dependency change | any | `package.json`, lockfiles, `requirements*.txt`, `go.mod`, `Cargo.toml`, `Gemfile`, `composer.json`. New transitive surface and new CVEs arrive through these. |
| Contract surface | `*.ts`/`*.proto`/`*.graphql` in the meaningful set | Type and schema changes break callers you cannot see from this repo. |

A change is **trivial** when none trigger, or when the diff is under 5 changed
lines with no sensitive path and no dependency change. Version bumps, generated
files, and doc edits land here even when the line count is large, because
`files_ignored` holds them out of the meaningful set first.

## The judgement call

The gate is mechanical on purpose: it has to be reproducible, or nobody trusts
it. When it fires on something that does not deserve a video, the fix is to
tune the thresholds in one place (`judge()` in `scripts/pr_brief.py`) and say so
in the PR thread, not to hand-wave the next one.

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
