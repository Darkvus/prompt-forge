import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SOURCE = "https://github.com/Darkvus/dev-toolkit"
MAX_DEFINITION_CHARS = 8_000
MAX_SOURCES = 5


@dataclass(frozen=True)
class Settings:
    """PROMPT_FORGE_LOCAL=1 is for your own machine: keys from .env are prefilled and local folders allowed.
    Without it (public deployment) every visitor must bring their own keys and only GitHub sources work."""
    local: bool
    sources: tuple[str, ...]
    keys: dict[str, str]
    github_token: str

    @classmethod
    def load(cls) -> "Settings":
        from app.llm import PROVIDERS

        local = os.getenv("PROMPT_FORGE_LOCAL") == "1"
        return cls(
            local=local,
            sources=tuple(s.strip() for s in os.getenv("SKILL_SOURCES", DEFAULT_SOURCE).split(",") if s.strip()),
            keys={name: os.getenv(p.env_key, "") for name, p in PROVIDERS.items()} if local else {},
            github_token=os.getenv("GITHUB_TOKEN", "") if local else "",
        )
