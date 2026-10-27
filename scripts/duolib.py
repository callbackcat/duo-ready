#!/usr/bin/env python3
"""Shared helpers for duo-ready scripts.

Standard library only: the Python that ships with Xcode's command line tools has
no PyYAML, and the skill must run on a fresh Mac without pip.

Public API (keep stable; every script imports it):
    load_yaml(path) / parse_yaml(text)   -- YAML subset used by duo.yaml and rules/*.yaml
    load_json(path) / write_json(path, obj)
    require_tool(name, hint)             -- exit 4 with "cannot run on this host" when missing
    host_is_macos()
    exit_codes                           -- names for the pipeline exit codes
    duo_dir(root) / run_dir(root, n) / next_run(root)
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Exit codes (see references/pipeline-contracts.md)
# ---------------------------------------------------------------------------


class exit_codes:  # noqa: N801 - used like a namespace
    PASS = 0
    UI_FAIL = 1
    PERF_FAIL = 2
    BUILD_FAIL = 3
    PREFLIGHT_FAIL = 4
    POSE_UNAVAILABLE = 5


def host_is_macos() -> bool:
    return platform.system() == "Darwin"


def require_tool(name: str, hint: str = "") -> str:
    """Return the tool's path or exit 4 with the contract's one-line message."""
    path = shutil.which(name)
    if path:
        return path
    msg = f"cannot run on this host: {name} not found"
    if hint:
        msg += f" ({hint})"
    print(msg, file=sys.stderr)
    sys.exit(exit_codes.PREFLIGHT_FAIL)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Working directory helpers
# ---------------------------------------------------------------------------


def duo_dir(root: str = ".") -> str:
    return os.path.join(root, ".duo")


def run_dir(root: str, n: int) -> str:
    return os.path.join(duo_dir(root), "runs", str(n))


def next_run(root: str = ".") -> int:
    runs = os.path.join(duo_dir(root), "runs")
    if not os.path.isdir(runs):
        return 1
    nums = [int(d) for d in os.listdir(runs) if d.isdigit()]
    return (max(nums) + 1) if nums else 1


# ---------------------------------------------------------------------------
# YAML subset parser
#
# Supported: nested maps and lists by 2-space (any consistent) indentation,
# "- item" lists, "- key: value" lists of maps, inline [a, b] lists and
# { k: v } maps, quoted strings with escapes, ints, floats, true/false/null,
# "#" comments. Not supported: anchors, multi-line scalars, flow nesting
# deeper than one level, tabs.
# ---------------------------------------------------------------------------


class YAMLError(ValueError):
    pass


@dataclass
class _Line:
    indent: int
    text: str
    no: int


_SCALAR_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d*$|^-?\d*\.\d+$")


def _strip_comment(text: str) -> str:
    out = []
    quote = None
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
            out.append(c)
        elif c == "#" and (i == 0 or text[i - 1] in " \t"):
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).rstrip()


def _scalar(tok: str) -> Any:
    tok = tok.strip()
    if tok == "":
        return None
    if tok[0] == '"' and tok[-1] == '"' and len(tok) >= 2:
        return bytes(tok[1:-1], "utf-8").decode("unicode_escape")
    if tok[0] == "'" and tok[-1] == "'" and len(tok) >= 2:
        return tok[1:-1].replace("''", "'")
    low = tok.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~"):
        return None
    if _SCALAR_RE.match(tok):
        return int(tok)
    if _FLOAT_RE.match(tok):
        return float(tok)
    if tok.startswith("[") and tok.endswith("]"):
        return [_scalar(p) for p in _split_flow(tok[1:-1])] if tok[1:-1].strip() else []
    if tok.startswith("{") and tok.endswith("}"):
        result: dict[str, Any] = {}
        for part in _split_flow(tok[1:-1]):
            if not part.strip():
                continue
            k, _, v = part.partition(":")
            result[k.strip().strip("'\"")] = _scalar(v)
        return result
    return tok


def _split_flow(body: str) -> list[str]:
    parts, buf, depth, quote = [], [], 0, None
    for c in body:
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            continue
        if c in ("'", '"'):
            quote = c
            buf.append(c)
        elif c in "[{":
            depth += 1
            buf.append(c)
        elif c in "]}":
            depth -= 1
            buf.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    if buf:
        parts.append("".join(buf))
    return parts


def _split_key(text: str) -> tuple[str, str] | None:
    """Split 'key: value' respecting quotes; return None if no key."""
    quote = None
    for i, c in enumerate(text):
        if quote:
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
        elif c == ":" and (i + 1 == len(text) or text[i + 1] in " \t"):
            key = text[:i].strip().strip("'\"")
            return key, text[i + 1 :].strip()
    return None


def parse_yaml(text: str) -> Any:
    lines: list[_Line] = []
    for no, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YAMLError(f"line {no}: tabs are not allowed for indentation")
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append(_Line(indent, stripped.strip(), no))
    if not lines:
        return {}
    value, idx = _parse_block(lines, 0, lines[0].indent)
    if idx != len(lines):
        raise YAMLError(f"line {lines[idx].no}: unexpected indentation")
    return value


def _parse_block(lines: list[_Line], idx: int, indent: int) -> tuple[Any, int]:
    if lines[idx].text.startswith("- ") or lines[idx].text == "-":
        return _parse_list(lines, idx, indent)
    return _parse_map(lines, idx, indent)


def _parse_map(lines: list[_Line], idx: int, indent: int) -> tuple[dict, int]:
    result: dict[str, Any] = {}
    while idx < len(lines) and lines[idx].indent == indent:
        ln = lines[idx]
        kv = _split_key(ln.text)
        if kv is None:
            raise YAMLError(f"line {ln.no}: expected 'key: value'")
        key, rest = kv
        if rest == "":
            # nested block or empty
            if idx + 1 < len(lines) and lines[idx + 1].indent > indent:
                value, idx = _parse_block(lines, idx + 1, lines[idx + 1].indent)
            elif idx + 1 < len(lines) and lines[idx + 1].indent == indent and lines[idx + 1].text.startswith("- "):
                # list at the same indentation as its key (common YAML style)
                value, idx = _parse_list(lines, idx + 1, indent)
            else:
                value, idx = None, idx + 1
        else:
            value, idx = _scalar(rest), idx + 1
        result[key] = value
    if idx < len(lines) and lines[idx].indent > indent:
        raise YAMLError(f"line {lines[idx].no}: unexpected indentation")
    return result, idx


def _parse_list(lines: list[_Line], idx: int, indent: int) -> tuple[list, int]:
    result: list[Any] = []
    while idx < len(lines) and lines[idx].indent == indent and (lines[idx].text.startswith("- ") or lines[idx].text == "-"):
        ln = lines[idx]
        body = ln.text[2:].strip() if ln.text != "-" else ""
        if body == "":
            if idx + 1 < len(lines) and lines[idx + 1].indent > indent:
                value, idx = _parse_block(lines, idx + 1, lines[idx + 1].indent)
            else:
                value, idx = None, idx + 1
            result.append(value)
            continue
        kv = _split_key(body)
        if kv is not None and not body.startswith(("[", "{", '"', "'")):
            # "- key: value" starts an inline map; its siblings are indented by 2
            item_indent = indent + 2
            key, rest = kv
            synthetic = [_Line(item_indent, body, ln.no)]
            j = idx + 1
            while j < len(lines) and lines[j].indent >= item_indent:
                synthetic.append(lines[j])
                j += 1
            if rest == "" and j - idx == 1 and (idx + 1 >= len(lines) or lines[idx + 1].indent <= indent):
                result.append({key: None})
                idx += 1
                continue
            value, consumed = _parse_map(synthetic, 0, item_indent)
            if consumed != len(synthetic):
                raise YAMLError(f"line {synthetic[consumed].no}: unexpected indentation in list item")
            result.append(value)
            idx = j
        else:
            result.append(_scalar(body))
            idx += 1
    return result, idx


def load_yaml(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        try:
            return parse_yaml(f.read())
        except YAMLError as e:
            raise YAMLError(f"{path}: {e}") from None


def dump_yaml(obj: Any, indent: int = 0) -> str:
    """Minimal emitter for duo.yaml scaffolds (maps, lists, scalars)."""
    pad = " " * indent
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                out.append(f"{pad}{k}:")
                out.append(dump_yaml(v, indent + 2))
            elif isinstance(v, list) and v and all(isinstance(i, dict) for i in v):
                out.append(f"{pad}{k}:")
                for item in v:
                    first = True
                    for ik, iv in item.items():
                        prefix = f"{pad}  - " if first else f"{pad}    "
                        out.append(f"{prefix}{ik}: {_emit_scalar(iv)}")
                        first = False
            elif isinstance(v, list):
                out.append(f"{pad}{k}: [{', '.join(_emit_scalar(i) for i in v)}]")
            else:
                out.append(f"{pad}{k}: {_emit_scalar(v)}")
    return "\n".join(line for line in out if line != "")


def _emit_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k}: {_emit_scalar(x)}" for k, x in v.items()) + " }"
    if isinstance(v, list):
        return "[" + ", ".join(_emit_scalar(i) for i in v) + "]"
    s = str(v)
    if s == "" or any(c in s for c in ":#[]{},\"'") or s.strip() != s or s.lower() in ("true", "false", "null", "yes", "no"):
        return json.dumps(s)
    return s
