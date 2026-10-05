# AGENTS.md

## What this repo is

Not an application. It is a single Hermes skill (`pr-motion-explainer`) plus the
artifacts that skill produced for this repo's own PR #1. The whole codebase is
~1100 lines of stdlib Python and its markdown.

The mental model to hold: **diff -> brief JSON -> two renderers**. `pr_brief.py`
is the only place that knows what a PR means; `render.py` and `poster.py` only
know the shape of a brief. Neither renderer ever reads git, `gh`, or a PR body
directly. When you need new information on screen, add it to the brief in
`pr_brief.py`, never by reaching into git from a renderer.

```
gh/git -> pr_brief.py --pr N | --range A...B  ->  brief.json
                                                      |
                          +-----------------------+---+--------------------+
                          |                                            |
              render.py  (animated HTML, --static, --mermaid)      poster.py (contact-sheet PNG)
```

## Commands

There is no build, no test runner, no linter config, and no CI. Everything runs
straight from the source files with `python3`. Verification is manual and is
described in `SKILL.md` under *Verification*; honour it rather than skipping it.

```bash
S=skills/software-development/pr-motion-explainer/scripts

# gate + storyboard (exit 3 = "skip, this diff is trivial" and is a valid answer)
python3 $S/pr_brief.py --pr 123 --out brief.json
python3 $S/pr_brief.py --range origin/main...HEAD --out brief.json   # no network
python3 $S/pr_brief.py --pr 123 --json-only                          # stderr silent

python3 $S/render.py brief.json --out out.html                       # animated
python3 $S/render.py brief.json --out out.html --static              # stacked, for print
python3 $S/render.py brief.json --mermaid --out comment.md           # PR-comment diagram
python3 $S/poster.py brief.json --out sheet.png                      # contact-sheet PNG
```

Quick repro of the committed demo (byte-for-byte, verified with `cmp`):

```bash
python3 $S/render.py docs/explainers/pr-1-brief.json --out docs/explainers/pr-1-pr-motion-explainer.html
python3 $S/poster.py docs/explainers/pr-1-brief.json --out docs/explainers/pr-1-contact-sheet.png
```

`ffmpeg` and `playwright` are **not** installed here. The mp4 route in
`references/publishing.md` is documented but untested; say so rather than
faking output. `gh` is available and authenticated; `git` obviously.

## Exit codes are load-bearing

`0` non-trivial, `3` trivial/empty (still writes a brief, with `beats: []`),
`1` fetch or usage error. Both `render.py` and `poster.py` exit `3` when the
brief has no beats. The `&&` chains the README recommends therefore depend on
this: `--force` on a trivial diff emits beats **and** exits `0`, so the chain
runs. If you change that, you break the documented usage.

## The gate is the product

`judge()` in `pr_brief.py` decides whether a diff deserves an explainer at all.
It has been rewritten several times because a misfired gate is worse than no
feature. Rules that exist because they were bugs:

- **Filter files before counting lines.** `judge()` sums added/deleted only over
  `meaningful` files. Counting the whole diff let a 900-line lockfile bump trip
  `MIN_CHANGED_LINES` on its own.
- **`triggers` and `missed` are separate lists.** A trigger is a threshold the
  diff met; folding a statement like "no meaningful files" into triggers made
  the verdict contradict its own reason. Do not merge them.
- **No line floor on the file-count trigger.** `MIN_FILES` fires at 3 files
  regardless of line count; only `MIN_LINES_FOR_SENSITIVE` gates the
  sensitive-path and dependency triggers.
- **`classify_files()` check order is intentional**: vendor/lockfile, then
  `DOC_ONLY` *minus* `MANIFEST` *minus* `DEPENDENCY_FILE`, then `CONFIG_NOISE`.
  `*.md` and `*.txt` are documentation by default, so `SKILL.md`/`README.md`
  and `requirements*.txt` must be carved back out or the file count and the
  dependency gate both break. Reordering these silently reintroduces old bugs.
- **Dotfile ordering.** git emits dotfiles first in a fresh diff, so
  `rank_for_lead()` sinks dotfiles and tests. Any new beat that picks a lead file
  must rank, not take `files[0]`.

Tuning a threshold is expected behaviour, not a hack: change it in `judge()`,
update `references/non-trivial.md`, and say in the PR thread which one moved.

## Beat content rules

Beat order is fixed in `BEAT_ORDER`: `problem, before, change, after, proof,
cost, recap`. Beats are **the script** - the workflow expects an agent to edit
`brief.json` by hand before rendering when a beat is vague. The
`problem`/`change`/`after` trio had a defect where all three read the same
`describe_shape()` clause, so watch for repetition across beats:

- `change` headline = what kind of change it is; the file list belongs in detail.
- `after` detail = where to start reading, not a restatement of the file list.

`proof` and `cost` are what keep the explainer honest ("no tests in the diff"
belongs on screen). `problem` comes from `first_problem_sentence()`, which skips
fixes/closes/##/what/why lines and accepts sentences of 20-220 chars; a body it
cannot parse yields "No description supplied.", which is a signal to write a
real PR description, not a placeholder to leave.

## Gotchas in `render.py`

- The timeline is CSS keyframes on fixed `vh`/`vw` boxes with a 30vh bottom
  inset reserved for the `.meta` strip. Raising `MAX_REFS_PER_SCENE` or
  `MAX_LINES_PER_REF` risks clipping; if you do, re-run the viewport check.
- Viewport sensitivity: below 760px tall the CSS tightens type; below 560px it
  hides `.ref-line` 4 and beyond. Verify at the shortest viewport you support.
- `--static` only injects `class="static"` into `<body>`; the CSS does the rest.
- `clip()` strips markdown from PR-body text. Anything inserted into the HTML
  must go through `esc()`; the output is committed and published.

## Gotchas in `poster.py`

- Pure stdlib PNG: a hand-rolled `Canvas`, a 5x7 bitmap `_FONT`, `struct`+`zlib`.
  No Pillow, no ImageMagick, no browser.
- Text wraps in **pixels** (`fit_cols`), not characters. Wrapping by character
  count is what previously made headlines wider than their card.
- Undefined glyphs render as a hollow box on purpose, so a missing glyph is
  visible instead of silently shortening the line. `plain()` folds to ASCII
  first, so non-Latin beat text is lost in the poster but survives in the HTML.
- Poster geometry targets a ~640px GitHub comment column, not a browser viewport.
- `ACCENT` here must stay in sync with `PALETTE` in `render.py`; the two artifacts
  are meant to read as the same piece.

## Browser check (required before publishing)

Seek each beat's midpoint with `document.getAnimations().forEach(a => { a.pause();
a.currentTime = ms })` where `ms = TITLE_SECONDS*1000 + i*SCENE_SECONDS*1000 +
SCENE_SECONDS*500`. Per beat: exactly one visible card, `scrollHeight -
clientHeight == 0`, and no intersection between the card's box and `.meta`.
If you have no browser, say the check was not performed; do not imply you looked.
`docs/explainers/frames/*.png` was captured this way and cannot be regenerated by
any shipped script.

## Conventions

- Python 3.9+ stdlib only. `from __future__ import annotations`, builtin
  generics, `argparse` with `RawDescriptionHelpFormatter` and the module
  `__doc__` as description.
- `gh`/`git` are called as subprocesses through a local `run()` helper.
- Human-readable output goes to **stderr**, data to stdout or `--out`. This is
  what makes `--json-only` meaningful.
- Comments explain *why* a rule exists, usually citing the bug that forced it.
  Match that density when you add code; the file reads as a changelog of fixes.
- Beat colours are keyed by beat name in both renderers; a new beat needs an
  entry in `PALETTE` and `ACCENT` or it falls back to grey.
- Docs are markdown with tables over prose; `README.md` carries the demo,
  `SKILL.md` the procedure, `references/` the reasoning behind the gate and the
  publishing rules.

## Repo-level gotchas

- The skill is also installed at `~/.config/.hermes/skills/software-development/pr-motion-explainer/`,
  which is where Hermes actually loads it from. **The installed copy wins.** After
  editing a script or `SKILL.md` here, re-copy the directory; a pre-fix installed
  copy has bitten this repo before. Verify with
  `diff -rq ~/.config/.hermes/skills/software-development/pr-motion-explainer/ skills/software-development/pr-motion-explainer/`.
- `.gitignore` deliberately ignores the scratch `brief.json` and `/*-explainer.html`
  but **not** `docs/explainers/`: published explainers must be committed because
  the skill links them from PR comments. Do not "tidy" that ignore rule.
- The scratch `brief.json` is not `docs/explainers/pr-1-brief.json`. The demo
  brief is committed precisely so a fresh checkout reproduces the artifacts.
- Published naming is `docs/explainers/pr-<N>-<title-slug>.html` plus
  `pr-<N>-contact-sheet.png`; one file per PR, overwrite rather than accumulate.
- Always pin links in a PR comment to the commit SHA, and use
  `raw.githubusercontent.com` (a blob URL renders source, not the animation).
  GitHub does not render inline HTML in comments, which is why mermaid + PNG lead.
- Generated explainer HTML/PNG goes in **its own commit**, separate from the
  feature change it describes.
- `.crush/` and `.cube/` are local session scratch (screenshots, browser
  profiles) and are ignored by global git config, not by this repo's
  `.gitignore`. Do not commit them.
