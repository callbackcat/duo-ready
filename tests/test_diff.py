import json
import os
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS)
import diff as d  # noqa: E402
import pngio  # noqa: E402


def make(path, w, h, color=(255, 255, 255), channels=3, rects=()):
    rows = pngio.solid(w, h, color, channels)
    for (x, y, rw, rh, c) in rects:
        pngio.fill_rect(rows, x, y, rw, rh, c, channels)
    pngio.write(path, w, h, channels, rows)
    return path


def test_png_roundtrip_all_channels(tmp_path):
    for ch in (1, 2, 3, 4):
        p = str(tmp_path / f"c{ch}.png")
        rows = pngio.solid(5, 4, (10, 20, 30, 40), ch)
        pngio.write(p, 5, 4, ch, rows)
        w, h, rch, back = pngio.read(p)
        assert (w, h, rch) == (5, 4, ch)
        assert back == rows
        inf = pngio.info(p)
        assert inf["has_alpha"] == (ch in (2, 4))


def test_png_filters_decode(tmp_path):
    # Build a PNG with each filter type by hand and make sure it decodes to the same rows.
    import struct
    import zlib

    w, h, ch = 4, 5, 3
    rows = [bytearray([(x * 37 + y * 11 + c * 5) & 0xFF for x in range(w) for c in range(ch)]) for y in range(h)]
    raw = bytearray()
    prev = bytearray(w * ch)
    for y, row in enumerate(rows):
        ftype = y % 5
        out = bytearray(row)
        for i in range(w * ch):
            a = row[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if ftype == 1:
                out[i] = (row[i] - a) & 0xFF
            elif ftype == 2:
                out[i] = (row[i] - b) & 0xFF
            elif ftype == 3:
                out[i] = (row[i] - ((a + b) >> 1)) & 0xFF
            elif ftype == 4:
                out[i] = (row[i] - pngio._paeth(a, b, c)) & 0xFF
        raw.append(ftype)
        raw += out
        prev = row
    p = str(tmp_path / "filters.png")
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(p, "wb") as f:
        f.write(pngio._SIGNATURE + pngio._chunk(b"IHDR", ihdr) + pngio._chunk(b"IDAT", zlib.compress(bytes(raw))) + pngio._chunk(b"IEND", b""))
    _, _, _, back = pngio.read(p)
    assert back == rows


def test_identical(tmp_path):
    a = make(str(tmp_path / "a.png"), 20, 20)
    b = make(str(tmp_path / "b.png"), 20, 20)
    res = d.compare(a, b)
    assert res["fraction"] == 0.0 and res["reason"] is None and res["total"] == 400


def test_changed_fraction_and_tolerance(tmp_path):
    a = make(str(tmp_path / "a.png"), 20, 20)
    b = make(str(tmp_path / "b.png"), 20, 20, rects=[(0, 0, 10, 20, (0, 0, 0))])
    assert d.compare(a, b)["fraction"] == pytest.approx(0.5)
    c = make(str(tmp_path / "c.png"), 20, 20, color=(245, 245, 245))  # within tolerance 16
    assert d.compare(a, c)["fraction"] == 0.0
    assert d.compare(a, c, tolerance=5)["fraction"] == 1.0


def test_size_mismatch(tmp_path):
    a = make(str(tmp_path / "a.png"), 20, 20)
    b = make(str(tmp_path / "b.png"), 21, 20)
    res = d.compare(a, b)
    assert res["fraction"] == 1.0 and "size mismatch" in res["reason"]


def test_ignore_region_and_out_image(tmp_path):
    a = make(str(tmp_path / "a.png"), 20, 20)
    b = make(str(tmp_path / "b.png"), 20, 20, rects=[(10, 0, 10, 20, (0, 0, 0))])
    out = str(tmp_path / "diff.png")
    res = d.compare(a, b, ignore=[(10, 0, 10, 20)], out=out)
    assert res["fraction"] == 0.0 and res["total"] == 200
    w, h, ch, rows = pngio.read(out)
    assert (w, h, ch) == (20, 20, 3)
    assert bytes(rows[0][15 * 3 : 15 * 3 + 3]) == b"\x40\x40\x40"  # ignored = grey
    res2 = d.compare(a, b, out=out)
    _, _, _, rows2 = pngio.read(out)
    assert bytes(rows2[0][15 * 3 : 15 * 3 + 3]) == b"\xff\x00\x00"  # changed = red
    assert res2["fraction"] == pytest.approx(0.5)


def test_rgba_vs_rgb(tmp_path):
    a = make(str(tmp_path / "a.png"), 8, 8, color=(1, 2, 3), channels=3)
    b = make(str(tmp_path / "b.png"), 8, 8, color=(1, 2, 3, 255), channels=4)
    assert d.compare(a, b)["fraction"] == 0.0


def test_cli_json_and_unreadable(tmp_path, capsys):
    a = make(str(tmp_path / "a.png"), 4, 4)
    code = d.main([a, str(tmp_path / "missing.png"), "--json"])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["fraction"] == 1.0 and "unreadable" in out["reason"]
    d.main([a, a])
    assert capsys.readouterr().out.strip() == "0.0000"
