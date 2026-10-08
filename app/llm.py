"""Provider-agnostic completion layer (OpenAI, Anthropic, Gemini). Keys are passed in by the caller and never stored."""
import json
import re
from dataclasses import dataclass, field

import anthropic
import openai


class LLMError(Exception):
    """Readable error that is safe to show to the user (never contains the API key)."""


@dataclass(frozen=True)
class Price:
    input: float  # USD per 1M tokens
    cached: float
    output: float


@dataclass(frozen=True)
class Provider:
    label: str
    env_key: str
    key_hint: str
    models: dict[str, Price | None]  # None = price unknown, cost shown as n/a
    fast: str
    write: str
    base_url: str | None = None


PROVIDERS: dict[str, Provider] = {
    "openai": Provider(
        "OpenAI", "OPENAI_API_KEY", "sk-...",
        {"gpt-5.5": Price(5.00, 0.50, 30.00), "gpt-5.4": Price(2.50, 0.25, 15.00),
         "gpt-5.4-mini": Price(0.75, 0.075, 4.50), "gpt-5-mini": Price(0.25, 0.025, 2.00)},
        fast="gpt-5.4-mini", write="gpt-5.4"),
    "anthropic": Provider(
        "Anthropic (Claude)", "ANTHROPIC_API_KEY", "sk-ant-...",
        {"claude-opus-5-5": Price(4.00, 0.20, 20.00), "claude-sonnet-5-5": Price(2.00, 0.20, 10.00),
         "claude-haiku-5-5": Price(0.10, 0.01, 0.50)},
        fast="claude-haiku-5-5", write="claude-sonnet-5-5"),
    "gemini": Provider(
        "Google Gemini", "GEMINI_API_KEY", "AIza...",
        {"gemini-2.5-pro": Price(1.25, 0.31, 10.00), "gemini-2.5-flash": Price(0.30, 0.075, 2.50),
         "gemini-2.5-flash-lite": Price(0.10, 0.025, 0.40)},
        fast="gemini-2.5-flash", write="gemini-2.5-pro",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"),
}
CUSTOM = "Otro (escribir id)…"


def price_for(provider: str, model: str) -> Price | None:
    models = PROVIDERS[provider].models
    if model in models:
        return models[model]
    known = [m for m in models if model.startswith(m + "-")]  # dated ids
    return models[max(known, key=len)] if known else None


@dataclass
class Usage:
    input: int = 0
    cached: int = 0
    output: int = 0
    usd: float = 0.0
    unpriced: bool = False


@dataclass
class Llm:
    """One configured model. `usage` can be shared between instances to total a whole run."""
    provider: str
    model: str
    api_key: str = field(repr=False)
    usage: Usage = field(default_factory=Usage)

    def complete(self, system: str, prefix: str, tail: str, max_tokens: int) -> str:
        """`prefix` is the large, reusable part of the user message (cacheable); `tail` varies per request."""
        try:
            if self.provider == "anthropic":
                return self._anthropic(system, prefix, tail, max_tokens)
            return self._openai_compatible(system, prefix, tail, max_tokens)
        except (openai.AuthenticationError, anthropic.AuthenticationError, openai.PermissionDeniedError,
                anthropic.PermissionDeniedError):
            raise LLMError(f"La clave de {PROVIDERS[self.provider].label} no es válida o no tiene permisos.") from None
        except (openai.RateLimitError, anthropic.RateLimitError):
            raise LLMError("Límite de uso o saldo agotado en tu cuenta. Revisa tu plan e inténtalo más tarde.") from None
        except (openai.NotFoundError, anthropic.NotFoundError):
            raise LLMError(f"El modelo '{self.model}' no existe o tu cuenta no tiene acceso.") from None
        except (openai.BadRequestError, anthropic.BadRequestError) as exc:
            raise LLMError(f"Petición rechazada por {PROVIDERS[self.provider].label}: {exc.message[:300]}") from None
        except (openai.APIConnectionError, anthropic.APIConnectionError):
            raise LLMError("No se pudo conectar con el proveedor.") from None
        except (openai.APIStatusError, anthropic.APIStatusError) as exc:
            raise LLMError(f"Error del proveedor ({exc.status_code}). Inténtalo de nuevo.") from None

    def _record(self, prompt: int, cached: int, output: int, cache_write: int = 0) -> None:
        u = self.usage
        u.input += prompt + cache_write
        u.cached += cached
        u.output += output
        price = price_for(self.provider, self.model)
        if price is None:
            u.unpriced = True
            return
        # Anthropic reports uncached input separately; cache writes cost 1.25x input.
        u.usd += (prompt * price.input + cache_write * price.input * 1.25 + cached * price.cached
                  + output * price.output) / 1e6

    def _openai_compatible(self, system: str, prefix: str, tail: str, max_tokens: int) -> str:
        client = openai.OpenAI(api_key=self.api_key, base_url=PROVIDERS[self.provider].base_url)
        kwargs = dict(model=self.model, max_completion_tokens=max_tokens, messages=[
            {"role": "system", "content": system}, {"role": "user", "content": f"{prefix}\n\n{tail}"}])
        try:  # low effort keeps hidden reasoning tokens (billed as output) small
            resp = client.chat.completions.create(reasoning_effort="low", **kwargs)
        except openai.BadRequestError:
            resp = client.chat.completions.create(**kwargs)
        u = resp.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        if u:
            self._record(u.prompt_tokens - cached, cached, u.completion_tokens)
        return (resp.choices[0].message.content or "").strip()

    def _anthropic(self, system: str, prefix: str, tail: str, max_tokens: int) -> str:
        client = anthropic.Anthropic(api_key=self.api_key)
        kwargs = dict(model=self.model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": [
            {"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": tail}]}])
        try:
            msg = client.messages.create(output_config={"effort": "low"}, **kwargs)
        except anthropic.BadRequestError:  # older models reject `effort`
            msg = client.messages.create(**kwargs)
        u = msg.usage
        self._record(u.input_tokens, u.cache_read_input_tokens or 0, u.output_tokens,
                     u.cache_creation_input_tokens or 0)
        return "".join(b.text for b in msg.content if b.type == "text").strip()


def parse_json_object(text: str) -> dict:
    """Extracts the first JSON object from a model reply (tolerates code fences and chatter)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMError("El modelo no devolvió JSON válido. Prueba con otro modelo.")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise LLMError("El modelo no devolvió JSON válido. Prueba con otro modelo.") from None
    if not isinstance(data, dict):
        raise LLMError("El modelo no devolvió JSON válido. Prueba con otro modelo.")
    return data
