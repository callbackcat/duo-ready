import json
import os
import struct
import sys

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS)
import assets_gate as g  # noqa: E402
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
