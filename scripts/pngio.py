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
        if ftype == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
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
