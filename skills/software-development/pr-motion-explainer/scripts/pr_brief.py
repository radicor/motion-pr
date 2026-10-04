#!/usr/bin/env python3
"""Build a motion-explainer storyboard brief from a pull request or a git range.

Two jobs, one JSON shape:

1. Decide whether the change is non-trivial enough to deserve an explainer
   (the skill's gate -- see references/non-trivial.md).
2. Turn the diff into ordered story beats a renderer can animate.

Usage
-----
    pr_brief.py --pr 123                       # via gh
    pr_brief.py --pr 123 --repo owner/name
    pr_brief.py --range origin/main...HEAD     # local, no network
    pr_brief.py --pr 123 --json-only           # stdout JSON, no human header

Output: JSON on stdout (a "storyboard brief"), human summary on stderr.
Exit codes: 0 non-trivial, 3 trivial (skip), 1 usage/fetch error.

No third-party dependencies: gh and git are invoked as subprocesses, all
parsing is stdlib.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# --- non-triviality gate -------------------------------------------------

# A change is non-trivial when it trips any of these. Tuned so that typo
# fixes, docs edits, and lockfile churn never reach a human reviewer as a
# video they have to sit through.
MIN_CHANGED_LINES = 40
MIN_FILES = 3

# The sensitive-path and dependency triggers fire on small diffs too often to be
# useful: a one-line typo in auth.py is not a story. They only count once the
# change has some real line mass behind it.
MIN_LINES_FOR_SENSITIVE = 8
SENSITIVE_PATH = re.compile(
    r"(^|/)(api|migrations?|schema|auth|oauth|session|billing|payment|"
    r"permissions?|crypto|token|security|index|query|cache|queue|"
    r"worker|middleware|router|entrypoint|main)\b|"
    r"\.(sql|graphql|proto|tf|ya?ml)$",
    re.I,
)
DEPENDENCY_FILE = re.compile(
    r"(^|/)(package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|"
    r"requirements[^/]*\.txt|poetry\.lock|go\.(mod|sum)|Cargo\.(toml|lock)|"
    r"Gemfile(\.lock)?|composer\.(json|lock))$",
    re.I,
)
DOC_ONLY = re.compile(r"(^|/)(docs?|documentation|examples?)/|\.(md|mdx|rst|txt)$", re.I)
LOCKFILE = re.compile(r"(-lock\.yaml|\.lock|package-lock\.json|poetry\.lock)$", re.I)
VENDOR = re.compile(r"(^|/)(vendor|third[_-]party|node_modules|dist|build)/", re.I)

# Dotfile config noise (.gitignore, .editorconfig) is never the story. Without this,
# a repo whose only non-doc change is a .gitignore gets that file as the lead beat.
CONFIG_NOISE = re.compile(r"(^|/)\.[A-Za-z0-9_-]+$|^(\.gitignore|\.editorconfig)$", re.I)

# SKILL.md and friends are the substance of a skill PR, not documentation of it.
# DOC_ONLY matches *.md, so carve skill/plugin manifests back out as meaningful.
MANIFEST = re.compile(r"(^|/)SKILL\.md$|(^|/)(AGENTS|CLAUDE|README)\.md$", re.I)

# Signalled file kinds -> story beat hints. First match wins, per file.
SIGNALS = [
    ("new endpoint", re.compile(r"(^|/)(routes?|controllers?|handlers?|endpoints?|api)/", re.I)),
    ("type or contract change", re.compile(r"\.(ts|tsx|d\.ts|proto|graphql)$", re.I)),
    ("schema or migration", re.compile(r"(^|/)(migrations?|schema|alembic|db)/|\.sql$", re.I)),
    ("auth or permissions", re.compile(r"(^|/)(auth|oauth|session|permissions?|policy)", re.I)),
    ("money path", re.compile(r"(^|/)(billing|payment|checkout|invoice|stripe)", re.I)),
    ("concurrency or hot loop", re.compile(r"(^|/)(worker|queue|scheduler|pool|thread|lock)", re.I)),
    ("cache or query path", re.compile(r"(^|/)(cache|query|index|search)", re.I)),
    ("infra or config", re.compile(r"(\.tf$|\.ya?ml$|\.toml$|(^|/)(infra|deploy|k8s|helm)/)", re.I)),
    ("tests", re.compile(r"(^|/)(tests?|spec|__tests__)/|\.(test|spec)\.", re.I)),
    ("ui or design", re.compile(r"\.(css|scss|less|vue|svelte|jsx|tsx|html)$|(^|/)(components?|ui|styles?)/", re.I)),
    ("build or release", re.compile(r"(^|/)(build|release|ci|\.github)/|Makefile|Dockerfile", re.I)),
]


def run(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


# --- diff collection -----------------------------------------------------


def classify_files(paths: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Split changed paths into (meaningful, ignorable, notable-signal labels)."""
    meaningful, ignorable, signals = [], [], []
    for p in paths:
        if VENDOR.search(p) or LOCKFILE.search(p):
            ignorable.append(p)
            continue
        # order matters: a manifest is meaningful even though it ends in .md
        if DOC_ONLY.search(p) and not MANIFEST.search(p):
            ignorable.append(p)
            continue
        if CONFIG_NOISE.search(p):
            ignorable.append(p)
            continue
        meaningful.append(p)
        for label, rx in SIGNALS:
            if rx.search(p):
                signals.append(label)
                break
    # keep signal order stable, first occurrence wins
    seen, ordered = set(), []
    for s in signals:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return meaningful, ignorable, ordered


def collect_files(diff_text: str) -> list[str]:
    paths = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                paths.append(path)
    return paths


def hunks(diff_text: str) -> list[dict]:
    """Parse the unified diff into hunks with the new-side line ranges.

    Good enough to point a beat at the code that actually moved.
    """
    out = []
    path, start, length = None, 0, 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1))
                length = int(m.group(2) or 1)
                out.append({"path": path, "start": start, "lines": length, "header": line.strip()})
        elif line.startswith("--- ") or line.startswith("diff --git"):
            path = path
    return out


def added_snippets(diff_text: str, per_file: int = 3) -> dict[str, list[str]]:
    """First few added lines per file, comments and defs preferred."""
    snips: dict[str, list[str]] = {}
    path = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            snips.setdefault(path, [])
        elif line.startswith("+") and not line.startswith("+++") and path:
            body = line[1:].rstrip()
            if len(snips[path]) < per_file and body.strip():
                snips[path].append(body.strip()[:110])
    return snips


def line_counts_by_file(diff_text: str) -> dict[str, tuple[int, int]]:
    """(added, deleted) per file, keyed by the same paths collect_files returns."""
    counts: dict[str, list[int]] = {}
    path = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                counts.setdefault(path, [0, 0])
        elif path is None:
            continue
        elif line.startswith("+") and not line.startswith("+++"):
            counts[path][0] += 1
        elif line.startswith("-") and not line.startswith("---"):
            counts[path][1] += 1
    return {p: (a, d) for p, (a, d) in counts.items()}


# --- beats ---------------------------------------------------------------

BEAT_ORDER = ["problem", "before", "change", "after", "proof", "cost", "recap"]


def build_beats(pr: dict, diff_text: str, files: list[str], signals: list[str],
                added: int, deleted: int) -> list[dict]:
    """Ordered beats. Each beat: name, headline, detail, code_refs."""
    meaningful, _, _ = classify_files(files)
    title = (pr.get("title") or "").strip()
    body = (pr.get("body") or "").strip()
    num = pr.get("number")
    snips = added_snippets(diff_text)
    changed_lines = added + deleted

    lead = rank_for_lead(meaningful)[0] if meaningful else (files[0] if files else "")
    headline = title or f"PR #{num}: {changed_lines} changed lines"

    beats = [
        {
            "name": "problem",
            "headline": title or (f"PR #{num}" if num else "Local change"),
            "detail": first_problem_sentence(body) or "No description supplied.",
            "code_refs": [],
        },
        {
            "name": "before",
            "headline": f"Before: {file_count_phrase(len(meaningful))}",
            "detail": f"{added} added / {deleted} removed across {len(meaningful)} meaningful files.",
            "code_refs": [{"path": lead, "hunks": [h for h in hunks(diff_text) if h["path"] == lead][:2]}]
            if lead else [],
        },
        {
            "name": "change",
            "headline": describe_change(signals, changed_lines, meaningful),
            "detail": "; ".join(signals) if signals else describe_shape(meaningful),
            "code_refs": [
                {"path": p, "added": snips.get(p, [])} for p in rank_for_lead(meaningful)[:3]
            ],
        },
        {
            "name": "after",
            "headline": f"After: {file_count_phrase(len(meaningful))} touched",
            "detail": f"Reviewer focus: {', '.join(signals[:3])}" if signals
            else f"Reviewer focus: {describe_shape(meaningful)}",
            "code_refs": [{"path": p} for p in rank_for_lead(meaningful)[:3]],
        },
    ]

    proof = [f for f in files if re.search(r"(^|/)(tests?|spec)/|\.(test|spec)\.", f, re.I)]
    beats.append({
        "name": "proof",
        "headline": f"Evidence: {len(proof)} test file(s) in the diff" if proof
        else "Evidence: no tests in the diff",
        "detail": ", ".join(proof[:3]) if proof else "Confirm the change manually before merge.",
        "code_refs": [{"path": p} for p in proof[:3]],
    })

    risks = [s for s in signals if s in
             ("schema or migration", "auth or permissions", "money path",
              "concurrency or hot loop", "cache or query path", "new endpoint")]
    beats.append({
        "name": "cost",
        "headline": f"Risk: {', '.join(risks[:2])}" if risks else "Risk: contained to the changed modules",
        "detail": rollback_note(pr, risks),
        "code_refs": [],
    })
    beats.append({
        "name": "recap",
        "headline": headline,
        "detail": f"{changed_lines} lines, {len(meaningful)} files"
                  + (f", #{num}" if num else ""),
        "code_refs": [],
    })
    return beats


def describe_change(signals: list[str], changed_lines: int,
                    files: list[str]) -> str:
    if signals:
        return f"Change: {signals[0]}"
    if changed_lines >= 200:
        return f"Change: {describe_shape(files)}"
    return "Change: focused edit"


def file_count_phrase(n: int) -> str:
    return "1 file" if n == 1 else f"{n} files"


def rank_for_lead(files: list[str]) -> list[str]:
    """Order files so the most reviewable one leads the beats.

    Paths arrive from the diff in whatever order git emitted them, which puts
    .gitignore and top-level dotfiles first. A reviewer wants the module that
    actually changed behaviour, not the ignore list.
    """
    def score(p: str) -> tuple:
        dotfile = 1 if CONFIG_NOISE.search(p) else 0
        test = 1 if re.search(r"(^|/)(tests?|spec)/|\.(test|spec)\.", p, re.I) else 0
        # tests and dotfiles sink; code files rise
        return (dotfile or test, -len(p.split("/")), p)
    return sorted(files, key=score)


def describe_shape(files: list[str]) -> str:
    """One honest clause about a diff that trips no path signal.

    "logic change spread across the diff" is the kind of sentence that makes a
    reviewer stop watching. Name the actual files instead.
    """
    if not files:
        return "no reviewable files in the diff"
    ranked = rank_for_lead(files)
    lead = ranked[0].rsplit("/", 1)[-1]
    if len(ranked) == 1:
        return f"everything lands in {lead}"
    others = [p.rsplit("/", 1)[-1] for p in ranked[1:4]]
    tail = ", ".join(others[:-1]) + (" and " + others[-1] if len(others) > 1 else "")
    return f"{lead} leads, with {tail}"


def first_problem_sentence(body: str) -> str:
    """First sentence that sounds like motivation, not boilerplate."""
    skip = re.compile(r"^(fixes|closes|resolves|co-authored-by|see also|##|what|why)\b", re.I)
    for para in body.split("\n\n"):
        text = " ".join(para.split())
        if not text or text.startswith("#") or text.startswith("|"):
            continue
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if 20 <= len(sent) <= 220 and not skip.match(sent) and not sent.startswith("-"):
                return sent
    return ""


def rollback_note(pr: dict, risks: list[str]) -> str:
    labels = pr.get("labels") or []
    for l in labels:
        if re.search(r"breaking", str(l), re.I):
            return "Labelled breaking: confirm a migration path and release note."
    if risks:
        return f"Reversible by reverting the commit; watch {risks[0]}."
    return "Single revert restores the previous behavior."


# --- gate ----------------------------------------------------------------


def judge(pr: dict, diff_text: str, files: list[str]) -> dict:
    counts = line_counts_by_file(diff_text)
    meaningful, ignorable, signals = classify_files(files)

    # Count only lines in files the gate did not already discard. A 900-line
    # lockfile bump is held out before the line threshold is applied, otherwise
    # the churn trips MIN_CHANGED_LINES on its own and a docs-only or vendored
    # diff animates anyway.
    added = sum(counts.get(p, (0, 0))[0] for p in meaningful)
    deleted = sum(counts.get(p, (0, 0))[1] for p in meaningful)
    changed = added + deleted

    reasons: list[str] = []
    missed: list[str] = []
    if not meaningful:
        reasons.append("no meaningful files (docs/lockfile/vendor only)")
    if changed >= MIN_CHANGED_LINES:
        reasons.append(f"{changed} changed lines >= {MIN_CHANGED_LINES}")
    else:
        missed.append(f"{changed} changed lines < {MIN_CHANGED_LINES}")
    if len(meaningful) >= MIN_FILES:
        reasons.append(f"{len(meaningful)} files >= {MIN_FILES}")
    else:
        missed.append(f"{len(meaningful)} meaningful file(s) < {MIN_FILES}")

    sensitive = [f for f in meaningful if SENSITIVE_PATH.search(f)]
    deps = [f for f in meaningful if DEPENDENCY_FILE.search(f)]
    enough_mass = changed >= MIN_LINES_FOR_SENSITIVE
    if sensitive and enough_mass:
        reasons.append("touches a sensitive path: " + ", ".join(sensitive[:2]))
    elif sensitive:
        missed.append(f"sensitive path {sensitive[0]} but only {changed} changed lines "
                      f"< {MIN_LINES_FOR_SENSITIVE}")
    if deps and enough_mass:
        reasons.append("dependency change: " + ", ".join(
            DEPENDENCY_FILE.sub("", d).split("/")[0] or d for d in deps[:2]))
    elif deps:
        missed.append(f"dependency change {deps[0]} but only {changed} changed lines "
                      f"< {MIN_LINES_FOR_SENSITIVE}")

    trivial = not reasons or (changed < 5 and not (sensitive and enough_mass)
                              and not (deps and enough_mass))

    # A trivial verdict has to say which threshold it came up against, otherwise
    # "too small to animate" gives the reader nothing to argue with or tune.
    if reasons:
        stated = reasons
    elif missed:
        stated = ["too small to animate: " + "; ".join(missed)]
    else:
        stated = ["too small to animate"]

    return {
        "non_trivial": not trivial,
        "added": added,
        "deleted": deleted,
        "changed_lines": changed,
        "files_total": len(files),
        "files_meaningful": meaningful,
        "files_ignored": ignorable,
        "signals": signals,
        "sensitive_paths": sensitive,
        "reasons": stated,
        "thresholds_missed": missed,
    }


# --- fetchers ------------------------------------------------------------


def fetch_pr(num: str, repo: str | None) -> tuple[dict, str]:
    base = ["gh", "pr", "view", num, "--json",
            "number,title,body,author,baseRefName,headRefName,labels,additions,deletions,changedFiles,url"]
    if repo:
        base += ["--repo", repo]
    rc, out, err = run(base)
    if rc != 0:
        sys.stderr.write(f"gh pr view failed: {err.strip()}\n")
        sys.exit(1)
    pr = json.loads(out)
    dcmd = ["gh", "pr", "diff", num]
    if repo:
        dcmd += ["--repo", repo]
    rc, diff, err = run(dcmd)
    if rc != 0:
        sys.stderr.write(f"gh pr diff failed: {err.strip()}\n")
        sys.exit(1)
    return pr, diff


def fetch_range(rng: str) -> tuple[dict, str]:
    rc, out, err = run(["git", "log", "--format=%H%x1f%s%x1f%b%x1e", rng])
    if rc != 0:
        sys.stderr.write(f"git log failed: {err.strip()}\n")
        sys.exit(1)
    raw = out.strip("\n")
    if not raw:
        sys.stderr.write("empty range\n")
        sys.exit(1)
    parts = raw.split("\x1e")[0].split("\x1f")
    commit = parts[0]
    rc, diff, err = run(["git", "diff", rng])
    if rc != 0:
        sys.stderr.write(f"git diff failed: {err.strip()}\n")
        sys.exit(1)
    pr = {
        "number": None,
        "title": parts[1] if len(parts) > 1 else "",
        "body": parts[2] if len(parts) > 2 else "",
        "labels": [],
        "author": {"login": ""},
        "url": "",
        "range": rng,
    }
    return pr, diff


# --- cli -------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pr", help="PR number (fetched with gh)")
    g.add_argument("--range", help="git range like origin/main...HEAD")
    ap.add_argument("--repo", help="owner/name for --pr")
    ap.add_argument("--out", help="write brief JSON here instead of stdout")
    ap.add_argument("--json-only", action="store_true", help="no human summary on stderr")
    ap.add_argument("--force", action="store_true", help="ignore the trivial verdict, still emit beats")
    args = ap.parse_args()

    if args.pr:
        pr, diff = fetch_pr(args.pr, args.repo)
    else:
        pr, diff = fetch_range(args.range)
    if not diff.strip():
        sys.stderr.write("diff is empty; nothing to explain\n")
        return 3

    files = collect_files(diff)
    verdict = judge(pr, diff, files)
    if not args.json_only:
        tag = "NON-TRIVIAL" if verdict["non_trivial"] else "TRIVIAL (skip the explainer)"
        print(f"[{tag}] PR {pr.get('number')} {pr.get('title') or ''}", file=sys.stderr)
        for r in verdict["reasons"]:
            print(f"  - {r}", file=sys.stderr)

    beats = []
    if verdict["non_trivial"] or args.force:
        beats = build_beats(pr, diff, files, verdict["signals"],
                            verdict["added"], verdict["deleted"])

    brief = {
        "source": {"pr": pr.get("number"), "url": pr.get("url"),
                   "title": pr.get("title"), "author": (pr.get("author") or {}).get("login"),
                   "base": pr.get("baseRefName"), "head": pr.get("headRefName"),
                   "range": pr.get("range")},
        "verdict": verdict,
        "beats": beats,
        "beat_order": BEAT_ORDER,
    }
    text = json.dumps(brief, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
        if not args.json_only:
            print(f"brief written to {args.out}", file=sys.stderr)
    else:
        print(text)
    # A forced run did the work, so it reports success. Returning 3 while the
    # beats sit in brief.json breaks a `pr_brief.py ... && render.py ...`
    # chain, which is how the usage docs tell people to run it.
    return 0 if (verdict["non_trivial"] or (args.force and beats)) else 3


if __name__ == "__main__":
    sys.exit(main())
