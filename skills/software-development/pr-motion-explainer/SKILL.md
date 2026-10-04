---
name: pr-motion-explainer
description: "Turn a non-trivial PR into an animated HTML explainer."
version: 1.0.0
author: Cube (radicor), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [pull-request, motion, explainer, video, animation, review, github]
    category: software-development
    related_skills: [github, requesting-code-review]
---

# PR motion explainer

Produce a short animated explainer for a pull request: decide whether the change
deserves one, build an ordered storyboard from the diff, render a self-contained
HTML file that plays the story on a fixed timeline, and publish it where a
reviewer will actually see it.

Everything is stdlib Python plus `git` and `gh`. No CDN, no build step, no
headless browser, no API keys. The output is one HTML file with inline CSS, so
it works offline, in a PR comment's preview cache, and as a screen-recording
source.

## When to use

Load this skill when:

- a pull request is non-trivial and a reviewer needs the shape of the change
  faster than they can read the diff
- you are asked for a "video", "animation", "motion graphic", "explainer", or
  "visual summary" of a change, branch, or release
- you want to check whether a diff is non-trivial before spending effort on it

Don't use for:

- typo fixes, version bumps, generated files, lockfile-only changes, doc edits
  (the gate rejects these; see `references/non-trivial.md`)
- a static architecture picture (use `architecture-diagram`)
- mathematical or algorithmic animation (use `manim-video`)

## Prerequisites

- `git` on PATH; `gh` authenticated (check with `gh auth status`) only when the
  source is a GitHub PR number. A local `git range` needs no network.
- Python 3.9+ from the session interpreter.

## How to Run

Two steps, always in this order.

```bash
# 1. gate + storyboard (exit 3 means "skip the explainer", which is a valid answer)
python3 <skill-dir>/scripts/pr_brief.py --pr 123 --repo owner/name --out brief.json

# 2. render the animated HTML
python3 <skill-dir>/scripts/render.py brief.json --out pr-123-explainer.html
```

`<skill-dir>` is this skill's directory, the parent of `scripts/`. Call
`skill_view(name='pr-motion-explainer')` to read the exact path for the session.

Use `--range origin/main...HEAD` instead of `--pr` for a local branch with no PR
yet; the beat content is identical, only the byline differs.

## Quick Reference

| Command | Effect |
|---|---|
| `pr_brief.py --pr N [--repo o/n]` | brief from a GitHub PR (`gh pr view` + `gh pr diff`) |
| `pr_brief.py --range A...B` | brief from a local git range, no network |
| `pr_brief.py ... --force` | emit beats even when the verdict is trivial |
| `pr_brief.py ... --json-only` | suppress the human summary on stderr |
| `render.py brief.json --out f.html` | animated timeline HTML |
| `render.py brief.json --out f.html --static` | stacked scenes for print / a static image |
| `render.py brief.json --mermaid --out m.md` | markdown mermaid beat chain, renders inline in the PR comment |
| `poster.py brief.json --out p.png` | contact-sheet PNG for the PR comment, pure stdlib |

Exit codes: `0` non-trivial, `3` trivial or empty diff, `1` fetch or usage error.


## Procedure

1. **Get the diff.** Either a PR number or a `git range`. Completion criterion:
   `pr_brief.py` printed a verdict line (`NON-TRIVIAL` or `TRIVIAL`) and
   `brief.json` exists.
2. **Respect the verdict.** If it says `TRIVIAL` and the user has not asked for a
   video anyway, stop and say why in one sentence, quoting the reason from
   `verdict.reasons`. On a trivial verdict that reason names the thresholds the
   diff came up against, so pass the numbers along rather than saying "too
   small". Do not render. Completion criterion: the user knows the gate fired
   and which threshold it missed.
3. **Read the beats before rendering.** `brief.json` holds ordered `beats`
   (`problem`, `before`, `change`, `after`, `proof`, `cost`, `recap`). Fix any
   beat that is wrong or vague by editing the brief JSON with `patch`; the beats
   are the script, and a vague `problem` sentence makes a vague video.
   Completion criterion: every headline is a specific claim rather than a
   restatement of the PR title.
4. **Render.** `render.py brief.json --out <path>`. Completion criterion: the
   script prints `N beats, Ms timeline` and the file exists at a plausible size
   (over 3KB for a 7-beat brief).
5. **Verify in a browser.** Open the file in whatever browser automation your
   session has, then seek the timeline per beat with
   `document.getAnimations().forEach(a => { a.pause(); a.currentTime = ms })`
   at each beat's midpoint. Confirm per beat: exactly one visible card,
   `scrollHeight - clientHeight == 0`, and no intersection between the card's
   bounding box and the `.meta` strip. Completion criterion: every beat checked,
   zero overflow, zero overlap.

   If you have no browser, say so plainly and check what you can statically:
   `poster.py` reads the same beats, so running it will catch a malformed brief
   before it reaches the PR. Report the unverified viewport check rather than
   implying you looked.
6. **Publish.** Follow `references/publishing.md`: commit the HTML and the
   contact-sheet PNG to the branch, then post a PR comment that leads with the
   mermaid beat chain (`render.py --mermaid`) and the PNG, with the raw HTML
   link after. GitHub renders mermaid and images inline; it will not render the
   HTML file itself. Completion criterion: the PR comment shows the diagram and
   the poster, and the links resolve from the branch you pushed.

## Beats

| Beat | Content | Source |
|---|---|---|
| `problem` | first motivational sentence of the PR body | `first_problem_sentence()` |
| `before` | file count and +/- totals, first hunk of the lead file | diff stats |
| `change` | the top signal (schema, auth, endpoint, ...) with real added lines | path signals + added snippets |
| `after` | the same file set read as a whole, plus reviewer focus | path signals |
| `proof` | test files that came with the diff, or a plain "no tests" | diff paths |
| `cost` | revert path, migration path when labelled breaking | labels + signals |
| `recap` | one-line summary | title + stats |

`proof` and `cost` are what keep the explainer honest. A `proof` beat that says
"no tests in the diff" belongs in the video, not buried in the description.

## Pitfalls

- **A trivial diff still renders if you force it.** `--force` exists for the
  three-line env flip that unblocks a deploy. Say in the PR comment that you
  forced it, and keep the beats short.
- **Beats are generated, not written.** The `problem` beat falls back to "No
  description supplied" when the PR body is empty. That sentence in a video is a
  reason to write a real description, not a placeholder to leave in place.
- **Viewport height matters.** Scenes are fixed-position boxes sized in `vh` and
  `vw`. Below 760px tall the CSS tightens type and trims code lines; below 560px
  it drops the third and later code lines entirely. If you raise
  `MAX_REFS_PER_SCENE` in `render.py`, re-run step 5 at the shortest viewport you
  support or the card will clip.
- **A dirty worktree changes the diff.** Some `git range` forms include
  uncommitted working-tree changes. Check `git status` before generating, or the
  explainer will describe code that was never in the PR.
- **`git range` beats have no PR number.** The byline falls back to the range
  string and the recap omits `#N`. Do not "fix" the missing number.

## Verification

- Gate: run `pr_brief.py` on a docs-only commit, on a one-line typo, and on a
  large lockfile-only bump; all three must exit `3`, and the reason must name
  the threshold the diff missed.
- Render: `render.py` exits `0`, prints the beat count, and the output contains
  one `<section class="scene">` per beat.
- Poster: `poster.py` exits `0` and writes a PNG whose header is
  `\x89PNG\r\n\x1a\n`. Open it once and look: text must sit inside its card, and
  a beat with no glyphs available must not turn into a row of empty boxes.
- Browser: at each beat's midpoint exactly one card is visible, `scrollHeight`
  equals `clientHeight`, and the card does not intersect `.meta`.
- Publish: the link in the PR comment loads the file you pushed, not a local
  path.