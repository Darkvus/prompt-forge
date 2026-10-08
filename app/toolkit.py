"""Loads skills and planner agents from a local dev-toolkit checkout."""
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Entry:
    kind: str  # "skill" | "agent"
    name: str
    description: str
    body: str

    @property
    def area(self) -> str:
        return self.name.split("-", 1)[0] if self.kind == "skill" else "agent"


def parse_markdown(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta = yaml.safe_load(match.group(1)) or {}
    return meta, match.group(2).strip()


def _load(path: Path, kind: str) -> Entry | None:
    meta, body = parse_markdown(path.read_text(encoding="utf-8"))
    name = meta.get("name") or path.parent.name if kind == "skill" else meta.get("name") or path.stem
    if not name:
        return None
    return Entry(kind, str(name), str(meta.get("description", "")).strip(), body)


def load_toolkit(root: Path) -> dict[str, Entry]:
    """Finds every `*/SKILL.md` and `agents/*.md` under root (any layout). Raises FileNotFoundError if none."""
    entries: dict[str, Entry] = {}
    for path in sorted(root.rglob("SKILL.md")):
        if "node_modules" not in path.parts and (entry := _load(path, "skill")):
            entries[entry.name] = entry
    for path in sorted(root.glob("**/agents/*.md")):
        if "node_modules" not in path.parts and (entry := _load(path, "agent")):
            entries.setdefault(entry.name, entry)
    if not entries:
        raise FileNotFoundError(f"No SKILL.md files or agents/ found in {root}")
    return entries


def load_sources(roots: list[Path]) -> dict[str, Entry]:
    """Merges several sources; on a name clash the later source wins."""
    merged: dict[str, Entry] = {}
    for root in roots:
        merged.update(load_toolkit(root))
    return merged


def linked_skills(entry: Entry, catalog: dict[str, Entry]) -> list[str]:
    """Skills referenced as [[name]] from an entry, in order of appearance."""
    seen: list[str] = []
    for name in re.findall(r"\[\[([\w-]+)\]\]", entry.body):
        if name in catalog and name != entry.name and name not in seen:
            seen.append(name)
    return seen


def skills_only(catalog: dict[str, Entry]) -> dict[str, Entry]:
    """Planner agents are long workflow prompts, not conventions; they cost tokens and add little."""
    return {n: e for n, e in catalog.items() if e.kind == "skill"}


def catalog_index(catalog: dict[str, Entry]) -> str:
    return "\n".join(f"- [{e.kind}] {e.name}: {e.description}" for e in catalog.values())
