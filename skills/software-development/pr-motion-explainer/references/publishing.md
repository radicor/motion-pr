# Publishing the explainer

The file is useless if it lives on your laptop. This is where it goes.

## The constraint

GitHub does not render `.html` files: a raw HTML URL in a PR comment shows
source, not the animation. There is no "attach the animation" path. So the PR
comment carries two things that render natively, plus the HTML link for anyone
who wants the motion:

1. **A mermaid snippet** (`render.py --mermaid`). GitHub renders `mermaid`
   fenced blocks in comments and descriptions, so the beat chain is visible
   inline. This is the in-thread summary.
2. **The contact-sheet PNG**, made by `scripts/poster.py` and linked by raw URL.
   Images render in comments; one 2x4 grid beats a paragraph. This is the
   in-thread poster.
3. **The HTML file**, committed and linked. It plays the actual timeline when
   opened. GitHub will not play it in place.
4. **An `.mp4`**, only when someone asks for a real video. ffmpeg is not a
   dependency of this skill.

A comment with (1) and (2) tells the reviewer the shape of the change without
leaving the PR. (3) is the full explainer.

## Path and commit

Commit next to what it explains, at a path that says what it is:

```
docs/explainers/pr-123-session-revocation.html
```

Use the PR number and a slug of the PR title. One file per PR; overwrite the
previous render if you re-render rather than committing a second copy.

The sha is the part people forget, and it is also the part that catches a stale
brief, so it is one input doing both jobs:

```bash
SHA=$(git rev-parse HEAD)
python3 <skill-dir>/scripts/render.py brief.json \
        --github --out docs/explainers/ --sha "$SHA"
git add docs/explainers/pr-123-*.html docs/explainers/pr-123-contact-sheet.png
git commit -m "docs: add motion explainer for #123"
git push
```

`--github` writes the animated HTML, the contact-sheet PNG, and a comment file
whose raw URLs are pinned to `$SHA`, then compares `$SHA` against the sha the
brief was gated from. If the branch moved between gating and publishing the
bundle is not written at all — the explainer would describe a diff that no
longer exists, which is worse than having none.

The manual commands still work and are what `--github` is doing:

```bash
python3 <skill-dir>/scripts/render.py brief.json --out docs/explainers/pr-123-session-revocation.html
python3 <skill-dir>/scripts/render.py brief.json --mermaid --out /tmp/comment.md
python3 <skill-dir>/scripts/poster.py brief.json \
        --out docs/explainers/pr-123-contact-sheet.png
```

Commit the contact-sheet PNG next to the HTML; the mermaid snippet itself is
inlined in the PR comment, so it needs no file of its own.

`poster.py` is stdlib only: it rasterises the brief itself with a built-in 5x7
font and writes the PNG directly, so it needs no headless browser, no
ImageMagick, and no Pillow even though none of those are dependencies of this
skill. It folds text to ASCII, so a beat written in a non-Latin script loses
those characters in the poster; the HTML still carries them.

Put it in its own commit. Mixing the generated HTML into the feature commit
makes the feature diff harder to read, which defeats the point of the video.

## The comment

Build the body from three parts: the mermaid beat chain, the contact-sheet PNG
as an image, and the pinned HTML link. `--github` writes exactly this to
`pr-<N>-comment.md`; the version below is what to write when you assemble it by
hand.

```bash
python3 <skill-dir>/scripts/render.py brief.json --mermaid --out /tmp/comment.md
SHA=$(git rev-parse HEAD)
{ cat /tmp/comment.md; echo; echo "![beats](https://raw.githubusercontent.com/owner/name/$SHA/docs/explainers/pr-123-contact-sheet.png)"; echo "[Animated explainer](https://raw.githubusercontent.com/owner/name/$SHA/docs/explainers/pr-123-....html)"; } > pr-123-comment.md
```

Then post what you read, after adding the one thing the video raised:

```bash
gh pr comment 123 --body-file pr-123-comment.md
```

The comment is a file rather than a direct post on purpose: the part worth
reading is the sentence a human writes about the diff, and that sentence does
not belong to a flag.

Use the raw content URL, not a blob URL, when you want the animation to run
rather than render as source:

```
https://raw.githubusercontent.com/owner/name/<sha>/docs/explainers/pr-123-....html
```

The `<sha>` matters. A URL on a moving ref can change under the reader if you
push a re-render. Pin to the commit SHA, then confirm the link actually
resolves before you call it posted. A blob URL renders the file's source, which
is fine for readers who want to audit the beats, so link both if the repo cares
about that.

## Optional: render to mp4

Only when someone asks for an actual video file. `ffmpeg` is not a dependency of
this skill, so check for it first and say so plainly if it is missing rather
than faking the output.

With a headless browser available, record the page at 30fps for the full
timeline (`TITLE_SECONDS + SCENE_SECONDS * beats`, printed by `render.py`):

```bash
# with playwright installed elsewhere; not installed by this skill
python -m playwright screenshot --viewport-size=1280,720 out.html frame.png
ffmpeg -framerate 30 -pattern_type glob -i 'frames/*.png' -c:v libx264 -pix_fmt yuv420p out.mp4
```

For a still image (release notes, a wiki page), render with `--static` and take
one screenshot instead. Static output stacks every scene, which is what you want
in a document and unusable as a video source.

## What to write in the PR comment

One line naming the beats and the runtime, the mermaid beat chain, the poster
image, the link, then anything the video cannot say: the things you want a human
to actually read.

> 7-beat explainer (31s)
>
> ```mermaid
> flowchart LR ...
> ```
>
> ![beats](…/pr-123-contact-sheet.png)
>
> [Animated explainer](…/pr-123-....html) — the beat that matters is `proof`:
> this diff ships no test for the revoked-session path. Happy to add one.

Do not paste the full PR description into the comment. The description is in the
diff; the video's job is the shape of the change, and the comment's job is the
one thing the video raised.