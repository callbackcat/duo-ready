import json
import os
import struct
import sys

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS)
import assets_gate as g  # noqa: E402
import featuring  # noqa: E402
import pngio  # noqa: E402


def png(path, w, h, channels=3):
    pngio.write(path, w, h, channels, pngio.solid(w, h, (255, 255, 255, 255), channels))


def jpeg(path, w, h):
    # minimal JPEG skeleton: SOI, APP0, SOF0 with dimensions, EOI (not decodable, enough for the marker parser)
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    with open(path, "wb") as f:
        f.write(b"\xff\xd8" + app0 + sof + b"\xff\xd9")


def test_accepts_all_four_sizes_and_jpeg(tmp_path):
    loc = tmp_path / "en-US"
    loc.mkdir()
    png(str(loc / "1_outer.png"), 1398, 2034)
    png(str(loc / "2_outer_land.png"), 2034, 1398)
    png(str(loc / "3_inner.png"), 2007, 2853)
    jpeg(str(loc / "4_inner_land.jpg"), 2853, 2007)
    res = g.gate(str(tmp_path))
    assert res["ok"], res["violations"]
    kinds = {(f["display"], f["orientation"]) for f in res["files"]}
    assert kinds == {("outer", "portrait"), ("outer", "landscape"), ("inner", "portrait"), ("inner", "landscape")}
    assert all(f["locale"] == "en-US" for f in res["files"])


def test_rejects_alpha_and_wrong_size(tmp_path):
    png(str(tmp_path / "alpha.png"), 1398, 2034, channels=4)
    png(str(tmp_path / "iphone69.png"), 1320, 2868)
    res = g.gate(str(tmp_path))
    assert not res["ok"]
    assert any("alpha" in v for v in res["violations"])
    assert any("iphone69.png" in i for i in res["ignored"])
    assert not any("iphone69.png" in v for v in res["violations"])
    strict = g.gate(str(tmp_path), strict=True)
    assert any("iphone69.png" in v for v in strict["violations"])


def test_trns_counts_as_alpha(tmp_path):
    p = str(tmp_path / "t.png")
    png(p, 1398, 2034)
    data = open(p, "rb").read()
    idat = data.index(b"IDAT") - 4
    trns = pngio._chunk(b"tRNS", b"\xff\xff\xff\xff\xff\xff")
    with open(p, "wb") as f:
        f.write(data[:idat] + trns + data[idat:])
    assert pngio.info(p)["has_alpha"]
    assert not g.gate(str(tmp_path))["ok"]


def test_per_locale_limit(tmp_path):
    loc = tmp_path / "de-DE"
    loc.mkdir()
    for i in range(11):
        png(str(loc / f"{i:02d}.png"), 1398, 2034)
    res = g.gate(str(tmp_path))
    assert any("limit is 10" in v for v in res["violations"])


def test_cli(tmp_path, capsys):
    png(str(tmp_path / "ok.png"), 2007, 2853)
    assert g.main([str(tmp_path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["files"][0]["display"] == "inner"
    assert g.main([str(tmp_path / "nope")]) == 1


def test_flatten_drops_alpha_and_keeps_pixels(tmp_path):
    """Field test 5, note 10: simctl captures are RGBA (opaque) and the gate
    rejected all six exported screenshots; assets.sh now flattens on export."""
    src = str(tmp_path / "cap.png")
    rows = pngio.solid(8, 4, (10, 20, 30, 255), 4)
    pngio.fill_rect(rows, 2, 1, 3, 2, (200, 100, 50, 128), 4)
    pngio.write(src, 8, 4, 4, rows)
    assert pngio.info(src)["has_alpha"]
    dst = str(tmp_path / "en-US" / "00_iphone_duo_outer_feed-closed-portrait.png")
    os.makedirs(os.path.dirname(dst))
    assert pngio.flatten(src, dst) is True
    inf = pngio.info(dst)
    assert inf["color_type"] == 2 and not inf["has_alpha"]
    w, h, ch, out = pngio.read(dst)
    assert (w, h, ch) == (8, 4, 3)
    assert bytes(out[0][:3]) == bytes((10, 20, 30)) and bytes(out[1][6:9]) == bytes((200, 100, 50))
    # an RGB source is left alone
    assert pngio.flatten(dst, str(tmp_path / "again.png")) is False
    # gray + alpha -> gray
    ga = str(tmp_path / "ga.png")
    pngio.write(ga, 4, 2, 2, pngio.solid(4, 2, (77, 255), 2))
    assert pngio.flatten(ga, str(tmp_path / "g.png")) and pngio.read(str(tmp_path / "g.png"))[2] == 1


def test_flattened_duo_capture_passes_the_gate(tmp_path):
    src = str(tmp_path / "cap.png")
    png(src, 1398, 2034, channels=4)
    loc = tmp_path / "shots" / "en-US"
    loc.mkdir(parents=True)
    pngio.flatten(src, str(loc / "00_iphone_duo_outer_feed-closed-portrait.png"))
    res = g.gate(str(tmp_path / "shots"))
    assert res["ok"] and res["files"][0]["display"] == "outer"


def test_reader_handles_every_filter_type(tmp_path):
    """The unfilter loops were rewritten for speed; check them against a
    hand-encoded image that uses filters 0 to 4 on successive rows."""
    import struct
    import zlib
    W, H, ch = 5, 5, 4
    rows = [bytearray(((x * 37 + y * 11 + c * 5) & 0xFF) for x in range(W) for c in range(ch)) for y in range(H)]

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        return a if pa <= pb and pa <= pc else (b if pb <= pc else c)

    raw = bytearray()
    prev = bytearray(W * ch)
    for y, line in enumerate(rows):
        f = y % 5
        raw.append(f)
        for i in range(W * ch):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            pred = {0: 0, 1: a, 2: b, 3: (a + b) >> 1, 4: paeth(a, b, c)}[f]
            raw.append((line[i] - pred) & 0xFF)
        prev = line
    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    p = str(tmp_path / "filters.png")
    with open(p, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))
    w, h, c, got = pngio.read(p)
    assert (w, h, c) == (W, H, ch) and [bytes(r) for r in got] == [bytes(r) for r in rows]


def _ui(cells):
    return {"schema": 1, "run": 17, "sdk_stamp": "27.1", "verified": True, "cells": cells}


def test_featuring_marks_a_run_with_failures_not_ready_and_claims_nothing_unproven():
    """Field test 6: the fixed template promised fold-safe controls while run 17
    had twelve interactive_in_fold failures."""
    ui = _ui([
        {"flow": "feed", "cell": "book-landscape", "results": [{"assertion": "interactive_in_fold", "status": "fail"},
                                                               {"assertion": "offscreen_elements", "status": "pass"}]},
        {"flow": "feed", "cell": "closed-portrait", "results": [{"assertion": "bars_vertical_expected", "status": "skip"},
                                                                {"assertion": "offscreen_elements", "status": "pass"}]},
        {"flow": "feed", "cell": "open-portrait", "results": [{"assertion": "offscreen_elements", "status": "warn"}]},
    ])
    text = featuring.build("DemoApp", 17, ui)
    assert text.startswith("# Featuring nomination: DemoApp on iPhone Duo")
    assert "Not ready to submit" in text and "feed / book-landscape (interactive_in_fold)" in text
    assert "clear of the fold" not in text  # the failed assertion earns no claim
    assert "vertical placement" not in text  # skip everywhere is not a pass
    assert "beyond the window edges" in text  # pass + warn, no fail
    assert "outer display when closed" in text and "book) pose" in text and "both orientations" in text
    assert "Split View" not in text and "iOS 27.1 SDK" in text
    assert "inner and outer displays" in text


def test_featuring_green_run_lists_the_proven_claims(tmp_path):
    ui = _ui([
        {"flow": "feed", "cell": "closed-portrait", "results": [{"assertion": "interactive_in_fold", "status": "pass"},
                                                                {"assertion": "transition_stable", "status": "pass"}]},
    ])
    text = featuring.build("DemoApp", 3, ui, displays=("outer",))
    assert "Not ready" not in text
    assert "clear of the fold in the book poses" in text and "survive folding and unfolding" in text
    assert "cover the outer display." in text and "both orientations" not in text
    # CLI writes the file and reports the state
    root = str(tmp_path)
    os.makedirs(os.path.join(root, ".duo", "runs", "3"))
    json.dump(ui, open(os.path.join(root, ".duo", "runs", "3", "ui.json"), "w"))
    assert featuring.main(["--run", "3", "--root", root, "--app", "DemoApp", "--displays", "outer"]) == 0
    assert "clear of the fold" in open(os.path.join(root, "FEATURING.md"), encoding="utf-8").read()
    # no ui.json at all: unproven, not a claim
    assert "unproven" in featuring.build("DemoApp", 4, None)
