# Publishing the explainer

The file is useless if it lives on your laptop. This is where it goes.

## The constraint

GitHub will not render inline video from a `<video>` tag with a relative path, and
a raw HTML file attached to a PR comment is not previewed either. So there is no
"attach the animation" path. The two that work:

1. **Commit the HTML to the branch and link it.** Universal, reviewable, diffable.
   Anyone with repo access can open it and the link survives in the thread
   forever.
2. **Render to a video and attach that**, when the repo wants a real `.mp4`.
   GitHub plays `<video src=...>` from a committed file in the PR comment.

Option 1 is the default. Option 2 needs `ffmpeg`, which this skill does not
require and does not install.

## Path and commit

Commit next to what it explains, at a path that says what it is:

```
docs/explainers/pr-123-session-revocation.html
```

Use the PR number and a slug of the PR title. One file per PR; overwrite the
previous render if you re-render rather than committing a second copy.

```bash
git add docs/explainers/pr-123-session-revocation.html
git commit -m "docs: add motion explainer for #123"
git push
```

Put it in its own commit. Mixing the generated HTML into the feature commit
makes the feature diff harder to read, which defeats the point of the video.

## The comment

```bash
gh pr comment 123 --body "Explainer (7 beats, 31s): <absolute-file-url>"
gh pr view 123
```

Use the raw content URL, not a blob URL, when you want the animation to run
rather than render as source:

```
https://raw.githubusercontent.com/owner/name/<sha>/docs/explainers/pr-123-....html
```

The `<sha>` matters. A URL on a moving ref can change under the reader if you
push a re-render. Pin to the commit SHA, then confirm the link with
`web_extract` before you call it posted. A blob URL renders the file's source,
which is fine for readers who want to audit the beats, so link both if the repo
cares about that.

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

One line naming the beats and the runtime, then the link, then anything the
video cannot say: the things you want a human to actually read.

> 7-beat explainer (31s): <url> — the beat that matters is `proof`: this diff
> ships no test for the revoked-session path. Happy to add one.

Do not paste the full PR description into the comment. The description is in the
diff; the video's job is the shape of the change, and the comment's job is the
one thing the video raised.