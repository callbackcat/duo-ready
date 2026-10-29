#!/usr/bin/env python3
"""Render a self-contained duo-report.html for one run.

    report.py --run <n> [--root .] [--json] [--out path]

Reads .duo/runs/<n>/{build.json,ui.json,perf.json,failures.json} and
.duo/scan.json, embeds screenshots as data URIs, and exits 1 on UI failures,
2 on perf failures, 0 otherwise. The report says which stages did not run so
nobody mistakes a skipped stage for a passing one. Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import shutil
import subprocess
import datetime as _dt
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import duolib  # noqa: E402
import pngio  # noqa: E402

CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mut:#6e6e73;--line:#d2d2d7;--pass:#1f8a3c;--warn:#b7791f;--fail:#c0392b;--skip:#8e8e93;--card:#f5f5f7}
@media (prefers-color-scheme:dark){:root{--bg:#1c1c1e;--fg:#f5f5f7;--mut:#a1a1a6;--line:#3a3a3c;--card:#2c2c2e}}
body{margin:0;padding:24px 16px;font:14px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg);max-width:1200px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 12px;border-bottom:1px solid var(--line);padding-bottom:6px}
.muted{color:var(--mut)}.note{background:var(--card);border-left:4px solid var(--warn);padding:10px 14px;border-radius:6px;margin:12px 0}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.matrix td{text-align:center;padding:4px}.matrix img{max-width:120px;max-height:120px;display:block;margin:4px auto;border:1px solid var(--line);border-radius:4px}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;color:#fff;font-size:12px}.pass{background:var(--pass)}.warn{background:var(--warn)}.fail{background:var(--fail)}.skip,.baseline,.info{background:var(--skip)}.unverified{background:var(--warn)}
.failure{background:var(--card);border-radius:8px;padding:12px;margin:12px 0;display:grid;grid-template-columns:minmax(200px,360px) 1fr;gap:16px}
.failure svg{width:100%;height:auto;border:1px solid var(--line);border-radius:4px}
.failure code{font-size:12px}.skipbox{background:var(--card);border:1px dashed var(--line);padding:12px;border-radius:8px}
ul{margin:4px 0;padding-left:20px}
@media (max-width:640px){.failure{grid-template-columns:1fr}}
"""

TIER_NOTES = {
    "27.1": "iOS 27.1 SDK: edge-to-edge, toolbars and tab bars vertical on the trailing edge, reserved regions reported.",
    "27.0": "iOS 27.0 SDK: fills most of the display but not under the status bar; no vertical bars. Rebuild with Xcode 27.1 before trusting these results.",
    "26": "iOS 26 or earlier SDK: app runs boxed in the centre of the inner display. Rebuild with Xcode 27.1 before trusting these results.",
}


def _load(path):
    return duolib.load_json(path) if os.path.exists(path) else None


def _data_uri(path: str) -> str | None:
    if not path or not os.path.exists(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")


# Full-size captures are 2007 x 2853 px; embedding every one of them twice made
# a 56 MB report on field test 2 (note 26). The report embeds thumbnails and
# links the full PNG on disk instead.
THUMB_MATRIX = 240   # longest edge, px, matrix cells
THUMB_FAILURE = 720  # longest edge, px, failure overlays


def _thumb_path(rdir: str, shot: str, edge: int) -> str:
    stem = os.path.splitext(os.path.basename(shot))[0]
    return os.path.join(rdir, "thumbs", f"{stem}.{edge}.png")


def _downscale_py(src: str, dst: str, edge: int) -> bool:
    """Nearest-neighbour downscale with the standard library (slow on big
    captures but needs nothing installed); sips is preferred on macOS."""
    try:
        w, h, ch, rows = pngio.read(src)
    except Exception:  # noqa: BLE001
        return False
    scale = max(w, h) / float(edge)
    if scale <= 1:
        shutil.copyfile(src, dst)
        return True
    nw, nh = max(1, int(w / scale)), max(1, int(h / scale))
    xs = [min(w - 1, int(x * scale)) * ch for x in range(nw)]
    out = []
    for y in range(nh):
        row = rows[min(h - 1, int(y * scale))]
        line = bytearray()
        for x0 in xs:
            line += row[x0:x0 + ch]
        out.append(line)
    pngio.write(dst, nw, nh, ch, out)
    return True


def thumbnail(rdir: str, shot: str, edge: int) -> str | None:
    """Path of a cached thumbnail of `shot` (longest edge `edge` px), made with
    sips on macOS and a pure-python fallback elsewhere; None when it cannot be made."""
    if not shot or not os.path.exists(shot):
        return None
    dst = _thumb_path(rdir, shot, edge)
    jpg = os.path.splitext(dst)[0] + ".jpg"
    for cached in (jpg, dst):
        if os.path.exists(cached) and os.path.getmtime(cached) >= os.path.getmtime(shot):
            return cached
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    size = _img_size(shot)
    if size and max(size) <= edge:
        shutil.copyfile(shot, dst)
        return dst
    if shutil.which("sips"):
        # JPEG on macOS: PNG thumbnails of 36 cells made a 4.1 MB report on
        # field test 3 (a 720 px failure overlay was 138 KB); JPEG is a quarter.
        r = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "70", "-Z", str(edge), shot, "--out", jpg],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(jpg):
            return jpg
        r = subprocess.run(["sips", "-Z", str(edge), shot, "--out", dst], capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dst):
            return dst
    return dst if _downscale_py(shot, dst, edge) else None


def _rel(root: str, path: str) -> str:
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path


def _img_size(path: str):
    try:
        inf = pngio.info(path)
        return inf["width"], inf["height"]
    except Exception:  # noqa: BLE001
        return None


def worst(statuses) -> str:
    order = {"fail": 3, "warn": 2, "pass": 1, "skip": 0}
    best = "skip"
    for s in statuses:
        if order.get(s, 0) > order[best]:
            best = s
    return best


def badge(status: str) -> str:
    return f'<span class="badge {html.escape(status)}">{html.escape(status)}</span>'


def overlay_svg(shot_path: str, elements, window, thumb_path: str | None = None) -> str:
    """SVG of the capture with element frames drawn over it. The image is the
    thumbnail when one is given (the viewBox stays in full-capture pixels so the
    frames line up); the full PNG is linked by the caller."""
    uri = _data_uri(thumb_path or shot_path)
    size = _img_size(shot_path) if shot_path else None
    if not uri or not size:
        return '<div class="muted">no screenshot</div>'
    iw, ih = size
    ww, wh = (window or [iw / 3, ih / 3])
    sx = iw / float(ww) if ww else 3.0
    sy = ih / float(wh) if wh else 3.0
    rects = []
    for el in elements or []:
        f = el.get("frame")
        if not f or len(f) != 4:
            continue
        x, y, w, h = [float(v) for v in f]
        rects.append(
            f'<rect x="{x*sx:.1f}" y="{y*sy:.1f}" width="{max(1,w*sx):.1f}" height="{max(1,h*sy):.1f}" '
            f'fill="rgba(192,57,43,0.25)" stroke="#c0392b" stroke-width="{max(2, iw/300):.0f}"><title>{html.escape(str(el.get("id","")))}</title></rect>'
        )
    return (f'<svg viewBox="0 0 {iw} {ih}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            f'<image href="{uri}" width="{iw}" height="{ih}"/>' + "".join(rects) + "</svg>")


def build_report(root: str, run: int) -> tuple[str, dict]:
    rdir = duolib.run_dir(root, run)
    cfg_path = os.path.join(root, "duo.yaml")
    cfg = duolib.load_yaml(cfg_path) if os.path.exists(cfg_path) else {}
    build = _load(os.path.join(rdir, "build.json"))
    ui = _load(os.path.join(rdir, "ui.json"))
    perf = _load(os.path.join(rdir, "perf.json"))
    failures = _load(os.path.join(rdir, "failures.json")) or []
    scan = _load(os.path.join(duolib.duo_dir(root), "scan.json"))

    app = (cfg or {}).get("scheme") or (build or {}).get("scheme") or os.path.basename(os.path.abspath(root))
    stamp = (build or {}).get("sdk_stamp") or (ui or {}).get("sdk_stamp")
    tier = (ui or {}).get("sdk_tier")
    if not tier:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from importlib import import_module
        tier = import_module("assert").sdk_tier(stamp)
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    ui_fail = bool(ui and any(r["status"] == "fail" for c in ui.get("cells", []) for r in c.get("results", [])))
    perf_fail = bool(perf and any(m.get("status") == "fail" for m in perf.get("metrics", [])))
    perf_skip = bool(perf) and not perf.get("metrics")
    ui_unverified = bool(ui) and ui.get("verified") is False

    skipped = []
    if build is None:
        skipped.append("build: no build.json, the app was not built by this run")
    if ui is None:
        cap_dir = os.path.join(rdir, "captures")
        if os.path.isdir(cap_dir) and any(n.endswith(".png") for n in os.listdir(cap_dir)):
            skipped.append("UI matrix: no ui.json, but captures exist: assert.py did not run (the matrix stopped early); "
                           f"run `scripts/assert.py --run {run}` to evaluate what was captured")
        else:
            skipped.append("UI matrix: no ui.json, no pose matrix was executed")
    if perf is None:
        skipped.append("performance: no perf.json, no metrics were collected")
    elif perf_skip:
        skipped.append("performance: perf.json has no metrics (" + str(perf.get("reason") or "DuoPerfTests target missing or nothing measured; perf.sh exit 4") + ")")
    if perf and perf.get("status") == "baseline":
        # perf.json says what perf.sh saw when it ran; the file may exist by now
        # (field test 6 read "no baseline" next to a baseline it had just promoted).
        if os.path.exists(os.path.join(duolib.duo_dir(root), "baselines", "perf.json")):
            skipped.append(f"performance: nothing was gated: perf.json for run {run} was written before "
                           ".duo/baselines/perf.json existed (or the baseline covers none of its cells); "
                           f"rerun perf.sh --run {run} to compare against it")
        else:
            skipped.append("performance: no baseline in .duo/baselines/perf.json, so nothing was gated; this run's numbers are "
                           f"the candidates (perf.sh --promote --run {run} records them without measuring again)")
    for m in (perf or {}).get("metrics", []) or []:
        if m.get("status") == "skip" and m.get("reason"):
            skipped.append(f"performance: {m.get('cell')}: {m.get('reason')}")
    if ui_unverified:
        skipped.append("UI matrix: no cell had an element tree (AXe not installed, or no DuoUITests attachment); "
                       "offscreen, clipped, tap-target, camera and fold assertions were skipped, not passed")
    errored = [c for c in (ui or {}).get("cells", []) if c.get("errored")]
    if errored:
        skipped.append(f"UI matrix: {len(errored)} cell(s) stopped on a flow step and have no capture: "
                       + ", ".join(f"{c['flow']}/{c['cell']}" for c in errored[:6]) + (" ..." if len(errored) > 6 else ""))
    axe_cells = [c for c in (ui or {}).get("cells", []) if c.get("ancestry") is False]
    if axe_cells:
        skipped.append("element trees came from duoctl elements (AXe): flat, no parent or scroll information, so "
                       "vertical overflow is reported as warn, not fail; the native DuoUITests tree is needed to fail it")
    if scan is None:
        skipped.append("scan: no .duo/scan.json")
    for note in (build or {}).get("skipped", []) or []:
        skipped.append(str(note))
    for note in (build or {}).get("host_notes", []) or []:
        skipped.append(str(note))
    if not any(c.get("results") and any(r["assertion"] == "visual_diff" and r["status"] != "skip" for r in c["results"]) for c in (ui or {}).get("cells", [])):
        skipped.append("visual diff: no baselines in .duo/baselines, nothing was compared")

    parts = [f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
             f"<title>duo-ready report {html.escape(str(app))} run {run}</title><style>{CSS}</style></head><body>"]
    parts.append(f"<h1>duo-ready report: {html.escape(str(app))}</h1>")
    parts.append(f'<div class="muted">run {run} · generated {now} · SDK stamp {html.escape(str(stamp or "unknown"))} (tier {html.escape(tier)})</div>')
    parts.append(f'<div class="note">{html.escape(TIER_NOTES.get(tier, ""))}<br>'
                 "App Store: iPhone Duo screenshots are optional today and become <strong>required from April 2027 for apps built with the iOS 27.1 SDK or later</strong>. "
                 "Apple has not said apps will be removed; submitting Duo screenshots now earns the “optimized for iPhone Duo” badge.</div>")

    if ui_fail or perf_fail:
        overall = "fail"
    elif ui_unverified:
        overall = "unverified"
    elif ui and any(r["status"] == "warn" for c in ui["cells"] for r in c["results"]):
        overall = "warn"
    else:
        overall = "pass" if ui else "skip"
    ui_badge = "fail" if ui_fail else ("unverified" if ui_unverified else ("pass" if ui else "skip"))
    perf_badge = "fail" if perf_fail else ("skip" if (perf is None or perf_skip) else ("baseline" if perf.get("status") == "baseline" else "pass"))
    parts.append(f"<p>Overall: {badge(overall)} &nbsp; UI {badge(ui_badge)} &nbsp; perf {badge(perf_badge)}</p>")

    # skipped stages
    parts.append('<h2>Unverified or skipped stages</h2><div class="skipbox">')
    if skipped:
        parts.append("<ul>" + "".join(f"<li>{html.escape(s)}</li>" for s in skipped) + "</ul>")
    else:
        parts.append("<div>All stages ran.</div>")
    parts.append("</div>")

    # matrix
    parts.append("<h2>Pose matrix</h2>")
    if ui and ui.get("cells"):
        flows = []
        cells = []
        for c in ui["cells"]:
            if c["flow"] not in flows:
                flows.append(c["flow"])
            if c["cell"] not in cells:
                cells.append(c["cell"])
        cfg_cells = list((cfg or {}).get("cells") or []) + list((cfg or {}).get("transitions") or [])
        cells.sort(key=lambda c: (cfg_cells.index(c) if c in cfg_cells else 99, c))
        lookup = {(c["flow"], c["cell"]): c for c in ui["cells"]}
        parts.append('<table class="matrix"><tr><th>flow</th>' + "".join(f"<th>{html.escape(c)}</th>" for c in cells) + "</tr>")
        for fl in flows:
            row = [f"<td><strong>{html.escape(fl)}</strong></td>"]
            for ce in cells:
                c = lookup.get((fl, ce))
                if not c:
                    row.append('<td class="muted">—</td>')
                    continue
                st = worst(r["status"] for r in c["results"])
                shot = os.path.join(root, c["screenshot"]) if c.get("screenshot") else None
                thumb = thumbnail(rdir, shot, THUMB_MATRIX) if shot else None
                uri = _data_uri(thumb) if thumb else None
                img = (f'<a href="{html.escape(_rel(rdir, shot))}" title="open the full capture"><img src="{uri}" alt="{html.escape(fl)} {html.escape(ce)}"></a>'
                       if uri else ('<div class="muted" style="font-size:11px">no capture</div>' if c.get("errored") else ""))
                bad = [r["assertion"] for r in c["results"] if r["status"] in ("fail", "warn")]
                extra = []
                if c.get("window_source") == "screenshot":
                    extra.append(f"window from capture {c.get('window')}")
                row.append(f"<td>{badge(st)}{img}<div class=\"muted\" style=\"font-size:11px\">{html.escape(', '.join(bad + extra))}</div></td>")
            parts.append("<tr>" + "".join(row) + "</tr>")
        parts.append("</table>")
    else:
        parts.append('<p class="muted">No UI results.</p>')

    # failures
    parts.append("<h2>Failures</h2>")
    if failures:
        window_lookup = {(c["flow"], c["cell"]): c.get("window") for c in (ui or {}).get("cells", [])}
        for f in failures:
            shot = os.path.join(root, f["screenshot"]) if f.get("screenshot") else None
            thumb = thumbnail(rdir, shot, THUMB_FAILURE) if shot else None
            svg = overlay_svg(shot, f.get("elements"), window_lookup.get((f["flow"], f["cell"])), thumb)
            link = f'<div class="muted" style="font-size:11px"><a href="{html.escape(_rel(rdir, shot))}">full capture</a></div>' if shot and os.path.exists(shot) else ""
            els = "".join(f"<li><code>{html.escape(str(e.get('id')))}</code> {html.escape(str(e.get('frame') or ''))}</li>" for e in f.get("elements") or [])
            hint = f.get("fix_hint") or ""
            src = f.get("source_hint")
            rule = f.get("matched_rule")
            conf = f.get("source_confidence")
            reason = f.get("reason")
            cause = ""
            if rule:
                how = {"file": "the screen's name matches the file", "rule": "a rule that causes this assertion is present in the scan"}.get(conf, "")
                cause = (f'<div>Likely cause: scan rule <code>{html.escape(rule)}</code> at <code>{html.escape(src or "")}</code>'
                         + (f' <span class="muted">({html.escape(how)})</span>' if how else "") + "</div>")
            parts.append(
                f'<div class="failure"><div>{svg}{link}</div><div>'
                f'<div>{badge(f.get("status","fail"))} <strong>{html.escape(f["flow"])}</strong> / {html.escape(f["cell"])} · <code>{html.escape(f["assertion"])}</code></div>'
                + (f'<div>{html.escape(str(reason))}</div>' if reason else "")
                + f"<ul>{els}</ul>"
                + cause
                + f'<div class="muted">{html.escape(hint)}</div></div></div>'
            )
    else:
        parts.append('<p class="muted">No failures recorded.</p>')

    # perf
    parts.append("<h2>Performance</h2>")
    if perf and perf.get("metrics"):
        parts.append(f'<div class="muted">mode: {html.escape(str(perf.get("mode", "regression")))} · simulator numbers are regression signals, not device numbers</div>')
        parts.append("<table><tr><th>flow</th><th>cell</th><th>metric</th><th>value</th><th>baseline</th><th>status</th></tr>")
        for m in perf["metrics"]:
            parts.append(f"<tr><td>{html.escape(str(m.get('flow','')))}</td><td>{html.escape(str(m.get('cell','')))}</td><td>{html.escape(str(m.get('metric','')))}</td>"
                         f"<td>{html.escape(str(m.get('value')) if m.get('value') is not None else '—')}</td><td>{html.escape(str(m.get('baseline') if m.get('baseline') is not None else '—'))}</td>"
                         f"<td>{badge(str(m.get('status','skip')))}{(' <span class=\"muted\">' + html.escape(str(m.get('reason'))) + '</span>') if m.get('reason') else ''}</td></tr>")
        parts.append("</table>")
    else:
        parts.append('<p class="muted">No performance data.</p>')

    # scan
    parts.append("<h2>Scan findings</h2>")
    if scan and scan.get("findings"):
        by_rule: dict[str, list] = {}
        for f in scan["findings"]:
            by_rule.setdefault(f.get("rule", "?"), []).append(f)
        parts.append("<table><tr><th>rule</th><th>severity</th><th>sites</th><th>autofix</th><th>example</th></tr>")
        for rule, fs in sorted(by_rule.items(), key=lambda kv: ({"error": 0, "warn": 1, "info": 2}.get(kv[1][0].get("severity"), 9), kv[0])):
            ex = fs[0]
            parts.append(f"<tr><td><code>{html.escape(rule)}</code></td><td>{badge({'error':'fail','warn':'warn','info':'skip'}.get(ex.get('severity'),'skip'))}</td>"
                         f"<td>{len(fs)}</td><td>{'yes' if ex.get('autofix') else 'no'}</td><td><code>{html.escape(str(ex.get('file','')))}:{html.escape(str(ex.get('line','')))}</code></td></tr>")
        parts.append("</table>")
    else:
        parts.append('<p class="muted">No scan findings.</p>')

    parts.append("</body></html>")
    summary = {
        "run": run, "app": app, "sdk_stamp": stamp, "sdk_tier": tier, "overall": overall,
        "ui_fail": ui_fail, "perf_fail": perf_fail, "failures": len(failures), "skipped": skipped,
    }
    return "".join(parts), summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", help="output path (default .duo/runs/<n>/duo-report.html)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    html_text, summary = build_report(args.root, args.run)
    out = args.out or os.path.join(duolib.run_dir(args.root, args.run), "duo-report.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_text)
    summary["report"] = out
    if args.json:
        print(json.dumps(summary))
    else:
        print(f"report written: {out}  overall={summary['overall']}  failures={summary['failures']}")
        for s in summary["skipped"]:
            print(f"  skipped: {s}")
    if summary["ui_fail"]:
        return duolib.exit_codes.UI_FAIL
    if summary["perf_fail"]:
        return duolib.exit_codes.PERF_FAIL
    if summary["overall"] in ("skip", "unverified"):
        # A run that measured nothing is not green (field test: run 1 was
        # "overall=skip, exit 0" after the app died at launch).
        print(f"report: nothing was verified (overall={summary['overall']}); exit 1 so a gate cannot read this as a pass", file=sys.stderr)
        return duolib.exit_codes.UI_FAIL
    return duolib.exit_codes.PASS


if __name__ == "__main__":
    sys.exit(main())
