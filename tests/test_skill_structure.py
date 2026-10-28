"""Structural checks for the skill itself: frontmatter, links, size limits."""
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SKILL = os.path.join(ROOT, "SKILL.md")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_frontmatter_has_name_and_description():
    text = _read(SKILL)
    assert text.startswith("---\n")
    end = text.index("\n---", 4)
    fm = text[4:end]
    assert re.search(r"^name: duo-ready$", fm, re.M)
    desc = re.search(r"^description: (.+)$", fm, re.M)
    assert desc and len(desc.group(1)) > 200, "description should be pushy and specific"
    assert "iPhone Duo" in desc.group(1)


def test_skill_body_under_500_lines():
    assert len(_read(SKILL).splitlines()) < 500


def test_every_referenced_file_exists():
    text = _read(SKILL)
    refs = set(re.findall(r'(?:`|\$DUO/)((?:references|scripts|templates)/[A-Za-z0-9_./-]+)[`"]', text))
    assert refs, "SKILL.md should route to references and scripts"
    missing = [r for r in refs if not os.path.exists(os.path.join(ROOT, r.split("#")[0]))]
    assert not missing, f"referenced but missing: {missing}"


def test_wording_rule():
    text = _read(SKILL).lower()
    assert "built with the ios 27.1 sdk or later" in text
    assert "never claim apps will be removed" in text


def test_no_em_dashes_in_skill():
    assert "—" not in _read(SKILL)


def test_plugin_and_marketplace_manifests_agree():
    """The repo is its own marketplace: `/plugin install duo-ready --marketplace callbackcat/duo-ready`."""
    import json
    plugin = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    market = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
    assert plugin["name"] == "duo-ready"
    assert re.fullmatch(r"\d+\.\d+\.\d+", plugin["version"])
    assert market["name"] == "callbackcat" and market["owner"]["name"]
    entries = {p["name"]: p for p in market["plugins"]}
    assert entries["duo-ready"]["source"] == "./"
    assert os.path.isfile(os.path.join(ROOT, ".claude-plugin", "icon.png"))
    # the skill locates its scripts through the variable Claude Code substitutes on load
    assert "${CLAUDE_SKILL_DIR}" in _read(SKILL)
