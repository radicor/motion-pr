#!/usr/bin/env python3
"""Render a storyboard brief into a self-contained animated HTML explainer.

Pure stdlib: brief JSON in, one HTML file out. No CDN, no build step, no
headless browser. The animation is CSS keyframes plus a scroll/timer driver,
so the result plays in any browser and in a PR comment via GitHub's camen
preview cache (see references/publishing.md for what does and does not work).

Usage
-----
    render.py brief.json --out pr-123-explainer.html
    render.py brief.json --out out.html --static     # stacked for print, no timeline
    render.py brief.json --mermaid --out comment.md   # beat chain for a PR comment
    render.py brief.json --github --out docs/explainers/ --sha <sha>

`--github` writes the HTML, the contact-sheet PNG, and a ready-to-post comment
whose raw URLs are pinned to `--sha`. The same sha is compared against the
brief's `source.head_sha`, so a brief whose diff has moved on is refused rather
than published. `--sha` on any other mode performs only that check.

Exit codes: 0 rendered, 3 no beats, 2 brief is not schema v2, 1 stale brief.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

from brief_schema import SCHEMA_VERSION, validate_brief
from poster import sheet as poster_sheet

# seconds per beat; also the CSS custom property the timeline is built from
SCENE_SECONDS = 4.0
TITLE_SECONDS = 3.0

# Fits a 1280x800 viewport: 6vw side margins. The page is a flex column, so the
# stage takes whatever height the meta strip leaves; raising these only risks
# clipping within the stage, never collision with the strip. Re-check the fit
# anyway (see SKILL.md Verification).
MAX_REFS_PER_SCENE = 3
MAX_LINES_PER_REF = 2

PALETTE = {
    "problem": ("#fb7185", "rgba(136,19,55,.35)"),
    "before": ("#94a3b8", "rgba(30,41,59,.45)"),
    "change": ("#22d3ee", "rgba(8,51,68,.45)"),
    "after": ("#34d399", "rgba(6,78,59,.45)"),
    "proof": ("#a78bfa", "rgba(76,29,149,.45)"),
    "cost": ("#fbbf24", "rgba(120,53,15,.40)"),
    "recap": ("#fb923c", "rgba(251,146,60,.40)"),
}


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def slugify(title: str) -> str:
    """PR title -> the `pr-N-<this>` filename half."""
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s[:48] or "change"


def owner_repo_from_url(url: str | None) -> tuple[str, str]:
    """github.com/owner/name/... -> (owner, name); empty when the brief has no URL."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url or "", re.I)
    return (m.group(1), m.group(2)) if m else ("", "")


def check_freshness(brief: dict, sha: str | None) -> str:
    """Does `--sha` match the sha this brief was gated from? Empty means fine.

    A stale explainer is worse than none: it states things about a diff that has
    moved. The renderers never run git, so the caller supplies the current sha
    and the comparison stays on this side of the architecture. Only checked when
    a sha is given -- re-rendering a committed brief for print has no reason to
    be fresh.
    """
    if not sha:
        return ""
    have = (brief.get("source") or {}).get("head_sha")
    if not have:
        return (f"no head_sha in the brief to compare against --sha {sha[:12]}; "
                "regenerate it with pr_brief.py")
    if have != sha:
        return (f"brief was gated from {have[:12]} but --sha is {sha[:12]}; "
                "the diff has moved on, re-run pr_brief.py")
    return ""


def clip(s: str, limit: int = 190) -> str:
    """Normalize markdown to plain text, then truncate to one readable line.

    Beats come from PR bodies, which are markdown. Backticks and bold survive
    into the video as literal characters, so strip them here rather than making
    every beat hand-cleaned.
    """
    text = (s or "").replace("`", "")
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^[-*+]\s+", "", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def title(verdict: dict) -> str:
    signals = verdict.get("signals") or []
    if signals:
        return signals[0]
    return f"{verdict.get('changed_lines', 0)} lines"


def mermaid_node(s: str) -> str:
    """Make text safe inside a mermaid node label."""
    text = clip(s, limit=90)
    return text.replace('"', "'").replace("[", "(").replace("]", ")")


def build_mermaid(brief: dict) -> str:
    """Markdown snippet whose mermaid block renders the beat chain inline.

    GitHub does not render HTML files, so the PR comment gets this diagram plus
    a link to the animated HTML. Beats become a left-to-right flow; the headline
    carries the information that would otherwise need the video.
    """
    beats = brief["beats"]
    verdict = brief["verdict"]
    src = brief["source"]
    byline = f"#{src['pr']}" if src.get("pr") else (src.get("range") or "")
    lines = ["```mermaid", "flowchart LR"]
    for i, b in enumerate(beats):
        label = f"{b['name']}: {mermaid_node(b['headline'])}"
        lines.append(f'    b{i}["{label}"]')
        if i:
            lines.append(f"    b{i - 1} --> b{i}")
    lines.append("```")
    stats = f"{verdict['changed_lines']} lines across {len(verdict['files_meaningful'])} files"
    header = f"**{mermaid_node(title(verdict))}** — {byline} · {stats} · {len(beats)} beats"
    return header + "\n\n" + "\n".join(lines) + "\n"


def build_html(brief: dict) -> str:
    src = brief["source"]
    verdict = brief["verdict"]
    beats = brief["beats"]
    total = TITLE_SECONDS + SCENE_SECONDS * len(beats)

    scenes = []
    for i, b in enumerate(beats):
        accent, fill = PALETTE.get(b["name"], ("#e2e8f0", "rgba(30,41,59,.45)"))
        delay = TITLE_SECONDS + i * SCENE_SECONDS
        refs = []
        for ref in b.get("code_refs", []):
            path = ref.get("path")
            if not path:
                continue
            hunks = ref.get("hunks") or []
            where = ", ".join(f"L{h['start']}" for h in hunks[:2]) if hunks else ""
            snippets = ref.get("added") or []
            inner = f'<span class="ref-path">{esc(path)}</span>'
            if where:
                inner += f'<span class="ref-where">{esc(where)}</span>'
            for s in snippets[:MAX_LINES_PER_REF]:
                inner += f'<code class="ref-line">{esc(s)}</code>'
            refs.append(inner)
        # cap refs per scene so the card never overflows its fixed viewport box
        refs = refs[:MAX_REFS_PER_SCENE]
        scenes.append(f"""
    <section class="scene" id="scene-{i}" style="--accent:{accent};--fill:{fill};--delay:{delay}s;--span:{SCENE_SECONDS}s">
      <div class="scene-tag">{esc(b['name'])}</div>
      <h2 class="scene-headline">{esc(b['headline'])}</h2>
      <p class="scene-detail">{esc(clip(b['detail']))}</p>
      <div class="refs">{''.join(refs) or '<span class="ref-empty">no file-level detail</span>'}</div>
      <div class="counter">{i + 1}/{len(beats)}</div>
    </section>""")

    reasons = "".join(f"<li>{esc(r)}</li>" for r in verdict.get("reasons", []))
    byline = f"#{src['pr']}" if src.get("pr") else (src.get("range") or "")
    pr_url = src.get("url") or ""
    linked = (f'<a href="{esc(pr_url)}">{esc(pr_url)}</a>') if pr_url else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PR {esc(byline)} explainer</title>
<style>
  :root {{
    --ink:#e2e8f0; --dim:#94a3b8; --bg:#020617; --card:#0b1220;
    --total:{total}s;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 "Inter",system-ui,-apple-system,"Segoe UI",sans-serif;
    /* the page is a column: the stage takes what is left once the meta strip
       has taken its own height, so the two can never overlap. The previous
       design fixed the meta over the stage and had the cards reserve a guessed
       30vh for it; a meta taller than the guess (three triggers rather than two)
       covered the last card by 2px at 577px and 17px at 560px. */
    display:flex; flex-direction:column; height:100vh; overflow:hidden;
  }}
  .stage {{
    position:relative; flex:1 1 auto; min-height:0; display:grid; place-items:center;
    overflow:hidden; background-image:
      linear-gradient(#111c33 1px,transparent 1px),
      linear-gradient(90deg,#111c33 1px,transparent 1px);
    background-size:40px 40px;
  }}
  /* in-flow now, so the card's bottom inset only has to clear the strip's top
    margin — a small constant, not a percentage of a height we do not control */
  .scene {{
    position:absolute; inset:7vh 6vw 2vh; padding:28px 32px; border-radius:14px;
    overflow:auto;
    background:var(--card); border:1px solid color-mix(in srgb, var(--accent) 45%, #1e293b);
    box-shadow:0 0 0 1px #0f172a, 0 30px 80px -40px var(--accent);
    opacity:0; visibility:hidden;
    animation:scene var(--span) linear var(--delay) both;
  }}
  @keyframes scene {{
    0%   {{ opacity:0; transform:translateY(14px) scale(.985); visibility:visible; }}
    8%   {{ opacity:1; transform:none; }}
    86%  {{ opacity:1; transform:none; }}
    100% {{ opacity:0; transform:translateY(-10px) scale(1.01); }}
  }}
  .scene-tag {{
    display:inline-block; font:11px/1 ui-monospace,Menlo,monospace;
    letter-spacing:.14em; text-transform:uppercase; color:var(--accent);
    border:1px solid var(--accent); border-radius:999px; padding:5px 10px;
  }}
  .scene-headline {{ margin:16px 0 8px; font-size:clamp(22px,3.4vw,38px); line-height:1.15; }}
  .scene-detail {{ margin:0; color:var(--dim); max-width:70ch; }}
  .refs {{ margin-top:22px; display:flex; flex-direction:column; gap:8px; max-width:78ch; }}
  .ref-path {{ font:12px/1.4 ui-monospace,Menlo,monospace; color:var(--accent); }}
  .ref-where {{ font:11px/1.4 ui-monospace,Menlo,monospace; color:#64748b; margin-left:10px; }}
  .ref-line {{
    display:block; padding:6px 10px; border-left:2px solid var(--accent);
    background:var(--fill); color:#cbd5e1; font:12px/1.45 ui-monospace,Menlo,monospace;
    white-space:pre-wrap; overflow-wrap:anywhere;
  }}
  .ref-empty {{ color:#475569; font-size:12px; }}
  .counter {{
    position:absolute; right:26px; bottom:20px; font:11px/1 ui-monospace,Menlo,monospace;
    color:#475569;
  }}
  .meta {{
    flex:0 0 auto; left:6vw; margin:0 6vw 3vh; max-width:60ch;
    font:12px/1.6 ui-monospace,Menlo,monospace; color:#64748b;
  }}
  .meta h1 {{ font:600 15px/1.4 system-ui,sans-serif; color:var(--ink); margin:0 0 6px; }}
  .meta a {{ color:#22d3ee; }}
  .meta ul {{ margin:8px 0 0; padding-left:18px; }}
  .bar {{
    position:fixed; left:0; top:0; height:2px; width:100%; transform-origin:0 50%;
    transform:scaleX(0); background:linear-gradient(90deg,#22d3ee,#a78bfa);
    animation:bar var(--total) linear both;
  }}
  @keyframes bar {{ from {{ transform:scaleX(0); }} to {{ transform:scaleX(1); }} }}
  .skip {{
    position:fixed; right:6vw; top:3vh; z-index:6; font:11px/1 ui-monospace,Menlo,monospace;
    color:#475569; border:1px solid #1e293b; border-radius:6px; padding:6px 8px;
  }}
  @media (prefers-reduced-motion: reduce) {{
    .scene {{ animation:none; opacity:0; }}
    .scene:nth-of-type(1) {{ animation:none; opacity:1; }}
    .bar {{ animation:none; }}
  }}
  .static {{ overflow:visible; height:auto; }}
  .static .scene {{ animation:none; position:relative; opacity:1; visibility:visible;
    inset:auto; margin:4vh 6vw; overflow:visible; }}
  .static .stage {{ flex:none; height:auto; display:block; }}
  .static .meta {{ margin-bottom:4vh; }}
  .static .bar {{ display:none; }}
  /* short viewports: tighten type and refs so a beat never clips its content */
  @media (max-height: 760px) {{
    .scene {{ inset:5vh 5vw 2vh; padding:18px 22px; }}
    .scene-tag {{ padding:4px 8px; font-size:10px; }}
    .scene-headline {{ margin:10px 0 6px; font-size:clamp(18px,2.4vw,26px); }}
    .scene-detail {{ font-size:13px; }}
    .refs {{ margin-top:12px; gap:5px; }}
    .ref-line {{ padding:4px 8px; font-size:11px; line-height:1.35; }}
    .ref-path {{ font-size:11px; }}
    .meta {{ font-size:11px; margin-bottom:2vh; }}
  }}
  @media (max-height: 560px) {{
    .scene {{ inset:4vh 5vw 2vh; padding:14px 18px; }}
    .refs .ref-line:nth-child(n+4) {{ display:none; }}
    .scene-headline {{ font-size:clamp(16px,2vw,22px); }}
  }}
</style>
</head>
<body>
<div class="bar"></div>
<div class="stage">{''.join(scenes)}</div>
<div class="skip">{total:.0f}s &middot; {len(beats)} beats</div>
<div class="meta">
  <h1>{esc(title(verdict))}</h1>
  <div>{esc(byline)} &middot; {verdict['changed_lines']} lines across
    {len(verdict['files_meaningful'])} files
    ({verdict['added']}+/{verdict['deleted']}-)</div>
  {f'<div>{linked}</div>' if linked else ''}
  <ul>{reasons}</ul>
</div>
</body>
</html>
"""


def publish_bundle(data: dict, out_dir: Path, sha: str | None) -> int:
    """Write the whole publish bundle: HTML, contact-sheet PNG, and a comment.

    Publishing used to be four commands and a copy-paste, which is where the
    contact sheet and the pinned sha got forgotten. One command emits
    everything `references/publishing.md` asks for.

    The raw URLs need a sha, and the same sha proves the brief is current, so
    passing `--sha` is what makes the bundle trustworthy. Without it the
    comment carries placeholders and no freshness check ran.
    """
    src = data["source"]
    beats = data["beats"]
    ident = str(src["pr"]) if src.get("pr") else (sha or "")[:8] or "local"
    prefix = f"pr-{ident}"
    slug = slugify(src.get("title"))
    owner, repo = owner_repo_from_url(src.get("url"))
    # placeholders, not guesses: a wrong owner/name silently links someone else's repo
    where = f"{owner}/{repo}" if owner else "<owner>/<repo>"
    pin = sha or "<sha>"

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{prefix}-{slug}.html"
    png_path = out_dir / f"{prefix}-contact-sheet.png"
    comment_path = out_dir / f"{prefix}-comment.md"

    html_path.write_text(build_html(data))
    png_path.write_bytes(poster_sheet(data))

    base = f"https://raw.githubusercontent.com/{where}/{pin}"
    body = build_mermaid(data)
    body += (
        f"\n![beats]({base}/{png_path.name})\n\n"
        f"[Animated explainer]({base}/{html_path.name})\n"
        f"\n<!-- add the one thing the video raised; see references/publishing.md -->\n"
    )
    comment_path.write_text(body)

    if not sha:
        sys.stderr.write("warning: no --sha, so the comment's raw URLs still hold "
                         "<sha> placeholders and were not freshness-checked\n")
    if not owner:
        sys.stderr.write("warning: the brief has no PR url, so the comment's raw "
                         "URLs still hold <owner>/<repo> placeholders\n")
    print(f"{out_dir}/: publish bundle for {prefix}-{slug}, {len(beats)} beats, "
          f"{TITLE_SECONDS + SCENE_SECONDS * len(beats):.0f}s", file=sys.stderr)
    for p in (html_path, png_path, comment_path):
        print(f"  {p.name}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brief", help="brief JSON from pr_brief.py")
    ap.add_argument("--out", help="output HTML path; with --github, the output directory (default docs/explainers)")
    ap.add_argument("--static", action="store_true",
                    help="stack the scenes for print/GitHub-image use, no timeline")
    ap.add_argument("--mermaid", action="store_true",
                    help="emit a markdown mermaid snippet (renders in the PR comment) instead of HTML")
    ap.add_argument("--github", action="store_true",
                    help="emit the whole publish bundle into --out: HTML, contact-sheet PNG, and a ready-to-post comment")
    ap.add_argument("--sha", help="commit SHA to pin raw URLs with, and to check against the brief's source.head_sha")
    args = ap.parse_args()

    data = json.loads(Path(args.brief).read_text())

    problems = validate_brief(data)
    if problems:
        sys.stderr.write(f"{args.brief}: not a v{SCHEMA_VERSION} brief\n")
        for p in problems:
            sys.stderr.write(f"  - {p}\n")
        return 2

    stale = check_freshness(data, args.sha)
    if stale:
        sys.stderr.write(f"{args.brief}: {stale}\n")
        return 1

    if not data.get("beats"):
        sys.stderr.write("brief has no beats (trivial PR? re-run with --force)\n")
        return 3

    if args.github:
        return publish_bundle(data, Path(args.out or "docs/explainers"), args.sha)

    if args.mermaid:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(build_mermaid(data))
        print(f"{args.out}: mermaid snippet, {len(data['beats'])} beats", file=sys.stderr)
        return 0
    doc = build_html(data)
    if args.static:
        doc = doc.replace("<body>", '<body class="static">', 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc)
    print(f"{args.out}: {len(data['beats'])} beats, "
          f"{TITLE_SECONDS + SCENE_SECONDS * len(data['beats']):.0f}s timeline", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
