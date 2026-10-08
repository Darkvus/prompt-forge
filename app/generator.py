"""Two-step generation: pick relevant toolkit entries, then write the Claude prompt."""
from dataclasses import dataclass

from app.llm import Llm, parse_json_object

from app.toolkit import Entry, catalog_index, linked_skills

MAX_CONTEXT_CHARS = 60_000  # ~15k tokens of skill text sent to the writer

SELECT_SYSTEM = """You are the router of a prompt-engineering tool. Given a project definition and a catalog of \
engineering skills/agents, choose the ones Claude Code must follow to build a high-quality proof of concept.
Rules: pick only entries whose conventions will actually be exercised by the PoC; prefer 4-10 entries; never invent \
names; skip backend entries for frontend-only ideas and vice versa; skip git/commit/dependency-governance entries \
unless the user asks for repo workflow. Also infer the stack."""

SELECT_FORMAT = """
Reply with ONLY a JSON object, no prose and no code fences:
{"entries": ["exact-name", ...], "stack_summary": "one sentence", "reasoning": "one or two sentences"}"""

WRITE_SYSTEM = """You are a senior staff engineer who writes prompts for Claude Code (an agentic coding CLI). \
Turn the project definition into ONE self-contained prompt that makes Claude build a high-quality, runnable \
proof of concept. You are given the team's engineering conventions (skills); the prompt must make Claude obey them.

Write the prompt in {language}. Output ONLY the prompt in Markdown, no preamble or commentary. Structure:
1. **Role & goal** - one paragraph.
2. **PoC scope** - in scope / explicitly out of scope (a PoC: thin vertical slice, real flow end to end, no gold-plating).
3. **Stack & architecture** - concrete choices and directory layout dictated by the conventions.
4. **Conventions to follow** - the concrete, checkable rules from the skills that apply (error envelope, units, \
PATCH-only updates, query params, structure, accessibility, etc.), distilled as short bullet rules. Cite each \
rule's source skill in backticks.
5. **Plan** - ordered phases; each phase has a goal, files to create, and acceptance criteria. Start with a \
short plan Claude must present before coding.
6. **Quality gates** - tests to write, lint/type-check/build commands Claude must run and pass; the PoC is not \
done until they pass. Tell Claude to run the app and verify the main flow, and to report anything unverified.
7. **Deliverables** - README with run steps, seed/demo data, list of known limitations and next steps.
{plugin_clause}
Rules: be specific and unambiguous, no filler; resolve small gaps in the definition with stated assumptions \
(list them under "Assumptions") instead of asking questions; do not invent conventions that are not in the \
provided skills; keep it under ~{max_words} words."""

PLUGIN_CLAUSE = """8. **Toolkit usage** - tell Claude that if the `dev-toolkit` plugin is installed it should invoke these \
skills/agents by name before the relevant phase: {names}. The prompt must still be fully usable without the plugin."""


@dataclass
class Selection:
    entries: list[str]
    stack_summary: str
    reasoning: str


@dataclass(frozen=True)
class Options:
    language: str = "English"
    size: str = "Standard"
    use_plugin_clause: bool = True
    expand_links: bool = True


WORDS = {"Compact": 900, "Standard": 1600, "Detailed": 2600}


MAX_OUTPUT = {"Compact": 3_000, "Standard": 5_000, "Detailed": 8_000}  # includes reasoning tokens


def select_entries(llm: Llm, definition: str, catalog: dict[str, Entry]) -> Selection:
    text = llm.complete(SELECT_SYSTEM + SELECT_FORMAT, f"# Catalog\n{catalog_index(catalog)}",
                        f"# Project definition\n{definition}", max_tokens=1_500)
    data = parse_json_object(text)
    entries = data.get("entries") if isinstance(data.get("entries"), list) else []
    valid = [n for n in dict.fromkeys(entries) if n in catalog]
    return Selection(valid, str(data.get("stack_summary", "")), str(data.get("reasoning", "")))


def expand(names: list[str], catalog: dict[str, Entry]) -> list[str]:
    """Adds skills linked from selected ones ([[x]]), one level deep, skills only."""
    out = list(names)
    for name in names:
        for linked in linked_skills(catalog[name], catalog):
            if catalog[linked].kind == "skill" and linked not in out:
                out.append(linked)
    return out


def build_context(names: list[str], catalog: dict[str, Entry], limit: int = MAX_CONTEXT_CHARS) -> tuple[str, list[str]]:
    """Concatenates entries until the char budget is hit. Returns (text, dropped names)."""
    parts, dropped, used = [], [], 0
    for name in names:
        entry = catalog[name]
        block = f"## {entry.kind.upper()}: {entry.name}\n{entry.description}\n\n{entry.body}"
        if used + len(block) > limit:
            dropped.append(name)
            continue
        parts.append(block)
        used += len(block)
    return "\n\n---\n\n".join(parts), dropped


def write_prompt(llm: Llm, definition: str, names: list[str], catalog: dict[str, Entry],
                 options: Options) -> tuple[str, list[str]]:
    final = expand(names, catalog) if options.expand_links else list(names)
    context, dropped = build_context(final, catalog)
    clause = PLUGIN_CLAUSE.format(names=", ".join(f"`{n}`" for n in final)) if options.use_plugin_clause else ""
    system = WRITE_SYSTEM.format(language=options.language, plugin_clause=clause, max_words=WORDS[options.size])
    # Skills first, definition last: the long shared prefix can be served from the provider's prompt cache.
    text = llm.complete(system, f"# Team conventions (skills)\n{context}", f"# Project definition\n{definition}",
                        max_tokens=MAX_OUTPUT[options.size])
    return text, dropped
