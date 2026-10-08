# Prompt Forge

Streamlit app: describe a PoC and get a self-contained prompt for Claude Code, grounded in the conventions of
any skills repo (default: [dev-toolkit](https://github.com/Darkvus/dev-toolkit)).

1. Skills are downloaded over HTTP from GitHub and suggested by keyword matching (no AI); optional AI suggestion with a cheap model. You always review the selection.
2. A strong model writes the final prompt with those skills as context (editable, downloadable).

Providers: **OpenAI, Anthropic (Claude), Google Gemini**, chosen independently per step, with a built-in cost estimate.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # PROMPT_FORGE_LOCAL=1 + your keys
streamlit run streamlit_app.py
pytest
```

## Publish on Streamlit Community Cloud (bring your own key)

1. Push this repo to GitHub (`.env` is git-ignored).
2. share.streamlit.io -> New app -> main file `streamlit_app.py`. It installs `requirements.txt`.
3. **Do not** set `PROMPT_FORGE_LOCAL` or any `*_API_KEY` secret. Without `PROMPT_FORGE_LOCAL=1` the app runs in
   public mode: every visitor types their own keys (held only in their session state), local folders and
   non-GitHub hosts are rejected, downloads are size-limited, and the disk cache is scoped per GitHub token so
   private repos are never shown to someone else.

Skill sources: a GitHub URL (`/tree/<branch>/<subfolder>` supported) or a `github.com` `.zip` link; any repo with
`SKILL.md` files works. Downloads are cached for 6 h; use *Actualizar fuentes* to refresh.
