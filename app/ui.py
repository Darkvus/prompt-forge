import urllib.error
import zipfile

import streamlit as st

from app.config import MAX_DEFINITION_CHARS, MAX_SOURCES, Settings
from app.generator import Options, expand, select_entries, write_prompt
from app.matcher import suggest
from app.llm import CUSTOM, PROVIDERS, Llm, LLMError, Usage
from app.sources import resolve
from app.toolkit import load_sources, skills_only

EXAMPLE = ("Panel interno para gestionar inventario de una tienda: listado de productos con búsqueda, "
           "filtros y paginación, alta/edición/borrado, y stock con alertas de bajo stock. "
           "API REST + interfaz web. Roles: admin y lector.")
FETCH_ERRORS = (OSError, ValueError, zipfile.BadZipFile, urllib.error.URLError)


@st.cache_data(show_spinner="Descargando skills...", ttl=3600, max_entries=20)
def cached_toolkit(sources: tuple[str, ...], token: str, refresh: int, local: bool):
    return load_sources([resolve(src, token or None, force=bool(refresh), local=local) for src in sources])


def model_picker(title: str, slot: str, default_provider: str, role: str) -> Llm:
    """Provider + model selector; the key is attached afterwards (one input per provider, shared by both steps)."""
    st.markdown(f"**{title}**")
    names = list(PROVIDERS)
    provider = st.selectbox("Proveedor", names, index=names.index(default_provider), key=f"{slot}_prov",
                            format_func=lambda n: PROVIDERS[n].label)
    info = PROVIDERS[provider]
    options = [*info.models, CUSTOM]
    default = getattr(info, role)
    choice = st.selectbox("Modelo", options, index=options.index(default), key=f"{slot}_{provider}_model",
                          format_func=lambda m: m if m == CUSTOM or info.models[m] is None
                          else f"{m} · ${info.models[m].input:g}/${info.models[m].output:g} por 1M")
    model = st.text_input("Id del modelo", key=f"{slot}_{provider}_custom") if choice == CUSTOM else choice
    return Llm(provider, model.strip(), "")


def main() -> None:
    st.set_page_config(page_title="Prompt Forge", page_icon="🛠️", layout="wide")
    settings = Settings.load()

    with st.sidebar:
        st.header("Configuración")
        st.caption("🔒 Usa tus propias claves. Solo viven en esta sesión del navegador; no se guardan en el servidor.")
        fast = model_picker("Sugerencia con IA (opcional, modelo barato)", "fast", "openai", "fast")
        writer = model_picker("Redactar el prompt (modelo potente)", "write", "anthropic", "write")
        st.markdown("**API keys**")
        for provider in dict.fromkeys((fast.provider, writer.provider)):  # one input per provider in use
            info = PROVIDERS[provider]
            key = st.text_input(info.label, type="password", placeholder=info.key_hint,
                                value=settings.keys.get(provider, ""), key=f"key_{provider}",
                                help="Se usa solo en tu sesión: no se guarda ni se registra.").strip()
            for llm in (fast, writer):
                if llm.provider == provider:
                    llm.api_key = key
        st.divider()
        language = st.selectbox("Idioma del prompt", ["English", "Español"])
        size = st.select_slider("Longitud", ["Compact", "Standard", "Detailed"], value="Standard")
        plugin_clause = st.checkbox("Mencionar skills del plugin", value=True,
                                    help="Pide a Claude invocar las skills si el plugin está instalado.")
        expand_links = st.checkbox("Incluir skills enlazadas ([[...]])", value=False,
                                   help="Más contexto = más coste. Puede arrastrar skills de otro stack.")
        with_agents = st.checkbox("Incluir agentes planificadores", value=False,
                                  help="Son prompts largos de workflow; encarecen mucho la llamada.")
        st.divider()
        sources_text = st.text_area(
            "Fuentes de skills (una por línea)", value="\n".join(settings.sources), height=100,
            help="URL de GitHub (admite /tree/rama/subcarpeta) o enlace .zip de github.com. "
                 "Vale cualquier repo con ficheros SKILL.md.")
        gh_token = st.text_input("GitHub token (solo repos privados)", type="password", value=settings.github_token,
                                 key="gh_token", help="Opcional. Solo se envía a GitHub y no se guarda.")
        if st.button("Actualizar fuentes"):
            st.session_state["refresh"] = st.session_state.get("refresh", 0) + 1

    sources = tuple(line.strip() for line in sources_text.splitlines() if line.strip())
    if not sources or len(sources) > MAX_SOURCES:
        st.error(f"Indica entre 1 y {MAX_SOURCES} fuentes de skills.")
        st.stop()
    try:
        catalog = cached_toolkit(sources, gh_token, st.session_state.get("refresh", 0), settings.local)
    except FETCH_ERRORS as exc:
        st.error(f"No se pudieron cargar las fuentes: {exc}")
        st.stop()
    if not with_agents:
        catalog = skills_only(catalog)

    skills = sum(e.kind == "skill" for e in catalog.values())
    st.title("🛠️ Prompt Forge")
    st.caption(f"Describe un PoC → prompt para Claude Code basado en tus skills · {skills} skills, "
               f"{len(catalog) - skills} agentes cargados")

    definition = st.text_area("Define tu PoC", value=st.session_state.get("definition", ""), height=180,
                              max_chars=MAX_DEFINITION_CHARS, placeholder=EXAMPLE)
    if st.button("Usar ejemplo"):
        st.session_state["definition"] = EXAMPLE
        st.rerun()

    usage: Usage = st.session_state.setdefault("usage", Usage())
    st.caption("Las skills se descargan por HTTP desde las fuentes y se muestran tal cual; la IA solo redacta el prompt.")
    c1, c2, _ = st.columns([1, 1.3, 3])
    if c1.button("1 · Sugerir skills", type="primary", disabled=not definition.strip(),
                 help="Coincidencia por palabras clave con el catálogo descargado. Sin IA, sin coste."):
        st.session_state.update(chosen=suggest(definition, catalog), sel_note="Sugerencia por palabras clave.")
    if c2.button("…o sugerir con IA", disabled=not definition.strip(),
                 help="Opcional: usa el modelo barato para elegir. Tiene coste."):
        if not fast.api_key:
            st.info(f"Introduce tu API key de {PROVIDERS[fast.provider].label} en la barra lateral.")
        else:
            fast.usage = usage
            try:
                with st.spinner("Analizando la definición..."):
                    sel = select_entries(fast, definition, catalog)
            except LLMError as exc:
                st.error(str(exc))
            else:
                st.session_state.update(chosen=[n for n in sel.entries if n in catalog],
                                        sel_note=f"**Stack:** {sel.stack_summary} — {sel.reasoning}")

    st.subheader("Skills a usar")
    if note := st.session_state.get("sel_note"):
        st.caption(note)
    # Drop stale choices (e.g. after changing sources) so the widget never holds names missing from the catalog.
    st.session_state["chosen"] = [n for n in st.session_state.get("chosen", []) if n in catalog]
    chosen = st.multiselect("Elige o ajusta las skills", list(catalog), key="chosen",
                            format_func=lambda n: f"{catalog[n].kind}: {n}")
    if expand_links and chosen:
        extra = [n for n in expand(chosen, catalog) if n not in chosen]
        if extra:
            st.caption("Se añadirán por enlace: " + ", ".join(extra))

    can_write = bool(definition.strip() and chosen and writer.api_key and writer.model)
    if not writer.api_key:
        st.info(f"Introduce tu API key de {PROVIDERS[writer.provider].label} para redactar el prompt.")
    if st.button("2 · Generar prompt", type="primary", disabled=not can_write):
        opts = Options(language, size, plugin_clause, expand_links)
        key = (definition, tuple(chosen), writer.provider, writer.model, opts)
        memo = st.session_state.setdefault("memo", {})
        try:
            if key not in memo:  # identical request: reuse the result instead of paying again
                writer.usage = usage
                with st.spinner("Redactando el prompt..."):
                    text, dropped = write_prompt(writer, definition, chosen, catalog, opts)
                memo[key] = (text, dropped)
            st.session_state["prompt"], st.session_state["dropped"] = memo[key]
        except LLMError as exc:
            st.error(str(exc))

    prompt = st.session_state.get("prompt")
    if prompt:
        st.subheader("Prompt para Claude Code")
        if st.session_state.get("dropped"):
            st.warning("Fuera del presupuesto de contexto: " + ", ".join(st.session_state["dropped"]))
        edited = st.text_area("Edita si hace falta", value=prompt, height=520, label_visibility="collapsed")
        c1, c2 = st.columns([1, 4])
        c1.download_button("Descargar .md", edited, file_name="claude-prompt.md", mime="text/markdown")
        u = usage
        cost = "n/d (modelo sin precio conocido)" if u.unpriced else f"≈ ${u.usd:.3f}"
        c2.caption(f"Tokens: {u.input:,} entrada ({u.cached:,} en caché) · {u.output:,} salida · {cost}")
        with st.expander("Vista previa / copiar"):
            st.code(edited, language="markdown")
