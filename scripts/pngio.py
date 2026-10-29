#!/usr/bin/env python3
"""Minimal PNG reader/writer (standard library only).

Supports 8-bit non-interlaced images with colour types 0 (gray), 2 (RGB),
4 (gray+alpha) and 6 (RGBA); all five scanline filters on read; filter 0 on
write. Enough for screenshot diffs and the App Store asset gate without
installing Pillow on a fresh Mac.

API:
    info(path) -> dict(width, height, bit_depth, color_type, channels, has_alpha, interlaced)
    read(path)  -> (width, height, channels, rows)   rows: list[bytearray], one per scanline
    write(path, width, height, channels, rows)       channels 1, 2, 3 or 4
    flatten(src, dst) -> bool                        drop the alpha channel (RGBA -> RGB, GA -> G)
    solid(width, height, rgb)                        helper returning rows for tests
"""
from __future__ import annotations

import struct
import zlib

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4, 3: 1}


class PNGError(ValueError):
    pass


def _chunks(data: bytes):
    if data[:8] != _SIGNATURE:
        raise PNGError("not a PNG file")
    pos = 8
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        yield ctype, body
        pos += 12 + length
        if ctype == b"IEND":
            break


def info(path: str) -> dict:
    with open(path, "rb") as f:
        data = f.read(64 * 1024)
    has_trns = False
    header = None
    for ctype, body in _chunks(data):
        if ctype == b"IHDR":
            w, h, depth, color, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body)
            header = (w, h, depth, color, interlace)
        elif ctype == b"tRNS":
            has_trns = True
        elif ctype == b"IDAT":
            break
    if header is None:
        raise PNGError("missing IHDR")
    w, h, depth, color, interlace = header
    return {
        "width": w,
        "height": h,
        "bit_depth": depth,
        "color_type": color,
        "channels": _CHANNELS.get(color, 0),
        "has_alpha": color in (4, 6) or has_trns,
        "interlaced": interlace == 1,
    }


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read(path: str):
    with open(path, "rb") as f:
        data = f.read()
    header = None
    idat = bytearray()
    for ctype, body in _chunks(data):
        if ctype == b"IHDR":
            w, h, depth, color, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body)
            header = (w, h, depth, color, interlace)
        elif ctype == b"IDAT":
            idat += body
    if header is None:
        raise PNGError("missing IHDR")
    w, h, depth, color, interlace = header
    if depth != 8:
        raise PNGError(f"unsupported bit depth {depth} (only 8)")
    if color not in (0, 2, 4, 6):
        raise PNGError(f"unsupported colour type {color}")
    if interlace:
        raise PNGError("interlaced PNG not supported")
    ch = _CHANNELS[color]
    raw = zlib.decompress(bytes(idat))
    stride = w * ch
    rows: list[bytearray] = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(h):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1 : pos + 1 + stride])
        pos += 1 + stride
        # Pure python, so a 2853 x 2007 capture takes seconds; the loops are
        # written for speed (no helper call per byte, zip for the Up filter).
        if ftype == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif ftype == 2:
            line = bytearray([(x + p) & 0xFF for x, p in zip(line, prev)])
        elif ftype == 3:
            for i in range(ch):
                line[i] = (line[i] + (prev[i] >> 1)) & 0xFF
            for i in range(ch, stride):
                line[i] = (line[i] + ((line[i - ch] + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(ch):
                line[i] = (line[i] + prev[i]) & 0xFF  # a = c = 0: paeth gives b
            for i in range(ch, stride):
                a = line[i - ch]
                b = prev[i]
                c = prev[i - ch]
                p = a + b - c
                pa = p - a if p >= a else a - p
                pb = p - b if p >= b else b - p
                pc = p - c if p >= c else c - p
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                line[i] = (line[i] + pred) & 0xFF
        elif ftype != 0:
            raise PNGError(f"bad filter type {ftype}")
        rows.append(line)
        prev = line
    return w, h, ch, rows


def _chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def write(path: str, width: int, height: int, channels: int, rows) -> None:
    color = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    raw = bytearray()
    for row in rows:
        if len(row) != width * channels:
            raise PNGError("row length does not match width*channels")
        raw.append(0)
        raw += bytes(row)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(_SIGNATURE)
        f.write(_chunk(b"IHDR", ihdr))
        f.write(_chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
        f.write(_chunk(b"IEND", b""))


def flatten(src: str, dst: str) -> bool:
    """Write `src` to `dst` without its alpha channel (RGBA -> RGB, gray+alpha
    -> gray). Returns False (and writes nothing) when `src` has no alpha.
    `xcrun simctl io screenshot` saves 8-bit RGBA PNGs with every alpha at 255;
    App Store Connect refuses any PNG with an alpha channel, so field test 5
    saw assets.sh reject all six of its own captures. The alpha values are
    dropped, not composited: a transparent pixel in an app screenshot has no
    defined background anyway."""
    meta = info(src)
    if not meta["has_alpha"]:
        return False
    w, h, ch, rows = read(src)
    if ch in (2, 4):
        for row in rows:
            del row[ch - 1 :: ch]
        ch -= 1
    write(dst, w, h, ch, rows)
    return True


def solid(width: int, height: int, rgb=(255, 255, 255), channels: int = 3):
    px = bytes(rgb[:channels]) if channels <= len(rgb) else bytes(rgb) + b"\xff" * (channels - len(rgb))
    return [bytearray(px * width) for _ in range(height)]


def fill_rect(rows, x: int, y: int, w: int, h: int, rgb, channels: int = 3) -> None:
    px = bytes(rgb[:channels]) if channels <= len(rgb) else bytes(rgb) + b"\xff" * (channels - len(rgb))
    for yy in range(max(0, y), min(len(rows), y + h)):
        row = rows[yy]
        width = len(row) // channels
        x0, x1 = max(0, x), min(width, x + w)
        if x1 > x0:
            row[x0 * channels : x1 * channels] = px * (x1 - x0)
