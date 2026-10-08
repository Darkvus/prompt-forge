"""Deterministic skill suggestion (no AI): keyword overlap between the definition and the fetched catalog."""
import re
import unicodedata

from app.toolkit import Entry

_STOP = set("""a al algo con como cual de del el en es esta este la las lo los para por que se su sus un una uno y o
the and for with that this from into are can has have its not you your our""".split())
# Signals for the two stacks; the catalog's own names (backend-*, frontend-*) decide where they apply.
_AREA_WORDS = {
    "backend": set("api rest backend servidor endpoint endpoints fastapi django drf microservicio microservicios "
                   "base datos database sql roles permisos autenticacion auth".split()),
    "frontend": set("web frontend interfaz ui react vite pagina paginas formulario formularios tabla tablas panel "
                    "dashboard pantalla pantallas shadcn listado".split()),
}
_ALIASES = {"tabla": "table", "tablas": "table", "formulario": "form", "formularios": "form", "permisos": "permission",
            "roles": "permission", "paginacion": "pagination", "filtros": "filter", "busqueda": "search",
            "listado": "list", "estructura": "structure", "pruebas": "testing", "tests": "testing",
            "accesibilidad": "accessibility", "tema": "theming", "colores": "theming"}


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    words = [w for w in re.findall(r"[a-z]{3,}", text) if w not in _STOP]
    return [_ALIASES.get(w, w) for w in words]


def suggest(definition: str, catalog: dict[str, Entry], limit: int = 8) -> list[str]:
    """Ranks skills by overlap with the definition; stack words boost the matching area. Returns names."""
    words = set(_tokens(definition))
    areas = {area: len(words & signal) for area, signal in _AREA_WORDS.items()}
    scores: dict[str, float] = {}
    for name, entry in catalog.items():
        if entry.kind != "skill":
            continue
        name_tokens = set(_tokens(name.replace("-", " ")))
        desc_tokens = set(_tokens(entry.description))
        score = 3 * len(words & name_tokens) + len(words & desc_tokens)
        if score:
            score += 2 * areas.get(entry.area, 0)  # same-area skills rise together
        scores[name] = score
    ranked = sorted((n for n, s in scores.items() if s > 0), key=lambda n: -scores[n])
    return ranked[:limit]
