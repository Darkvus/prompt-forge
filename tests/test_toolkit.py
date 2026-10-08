from pathlib import Path

import pytest

from app.generator import build_context, expand
from app.toolkit import load_sources, load_toolkit, parse_markdown


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for name, body in {"a": "uses [[b]] and [[nope]]", "b": "leaf"}.items():
        d = tmp_path / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f'---\nname: {name}\ndescription: "desc {name}"\n---\n# {name}\n{body}')
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "p.md").write_text("---\nname: p\ndescription: planner\n---\nbody")
    return tmp_path


def test_parse_without_frontmatter():
    assert parse_markdown("hello") == ({}, "hello")


def test_load_and_expand(root):
    catalog = load_toolkit(root)
    assert set(catalog) == {"a", "b", "p"}
    assert expand(["a"], catalog) == ["a", "b"]


def test_budget_drops_overflow(root):
    catalog = load_toolkit(root)
    text, dropped = build_context(["a", "b"], catalog, limit=60)
    assert dropped == ["b"] and "SKILL: a" in text


def test_missing_toolkit(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_toolkit(tmp_path)


def test_empty_source_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_toolkit(tmp_path)


def test_later_source_wins(root, tmp_path_factory):
    other = tmp_path_factory.mktemp("o")
    (other / "x").mkdir()
    (other / "x" / "SKILL.md").write_text("---\nname: a\ndescription: override\n---\nnew")
    assert load_sources([root, other])["a"].description == "override"
