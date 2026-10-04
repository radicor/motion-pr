#!/usr/bin/env python3
"""Render a storyboard brief into a self-contained animated HTML explainer.

Pure stdlib: brief JSON in, one HTML file out. No CDN, no build step, no
headless browser. The animation is CSS keyframes plus a scroll/timer driver,
so the result plays in any browser and in a PR comment via GitHub's camen
preview cache (see references/publishing.md for what does and does not work).

Usage
-----
    render.py brief.json --out pr-123-explainer.html
    render.py brief.json --out out.html --fps 30 --static     # no JS driver
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

# seconds per beat; also the CSS custom property the timeline is built from
SCENE_SECONDS = 4.0
TITLE_SECONDS = 3.0

# Fits a 1280x800 viewport: 6vw side margins, 30vh reserved for the meta strip.
# Raise these only if you also re-check the fit (see SKILL.md Verification).
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
  }}
  .stage {{
    position:relative; height:100vh; display:grid; place-items:center;
    overflow:hidden; background-image:
      linear-gradient(#111c33 1px,transparent 1px),
      linear-gradient(90deg,#111c33 1px,transparent 1px);
    background-size:40px 40px;
  }}
  /* bottom inset reserves the meta strip so nothing is ever occluded */
  .scene {{
    position:absolute; inset:7vh 6vw 30vh; padding:28px 32px; border-radius:14px;
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
    position:fixed; left:6vw; bottom:3vh; z-index:5; max-width:60ch;
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
  .static .scene {{ animation:none; position:relative; opacity:1; visibility:visible;
    inset:auto; margin:4vh 6vw; overflow:visible; }}
  .static .stage {{ height:auto; display:block; }}
  .static .bar {{ display:none; }}
  /* short viewports: tighten type and refs so a beat never clips its content */
  @media (max-height: 760px) {{
    .scene {{ inset:5vh 5vw 26vh; padding:18px 22px; }}
    .scene-tag {{ padding:4px 8px; font-size:10px; }}
    .scene-headline {{ margin:10px 0 6px; font-size:clamp(18px,2.4vw,26px); }}
    .scene-detail {{ font-size:13px; }}
    .refs {{ margin-top:12px; gap:5px; }}
    .ref-line {{ padding:4px 8px; font-size:11px; line-height:1.35; }}
    .ref-path {{ font-size:11px; }}
    .meta {{ font-size:11px; bottom:2vh; }}
  }}
  @media (max-height: 560px) {{
    .scene {{ inset:4vh 5vw 24vh; padding:14px 18px; }}
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("brief", help="brief JSON from pr_brief.py")
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument("--static", action="store_true",
                    help="stack the scenes for print/GitHub-image use, no timeline")
    args = ap.parse_args()

    data = json.loads(Path(args.brief).read_text())
    if not data.get("beats"):
        sys.stderr.write("brief has no beats (trivial PR? re-run with --force)\n")
        return 3
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
