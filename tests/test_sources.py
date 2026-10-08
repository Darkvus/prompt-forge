import io
import zipfile

import pytest

from app import sources


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "CACHE_DIR", tmp_path / "cache")


def test_local_path(tmp_path):
    assert sources.resolve(str(tmp_path), local=True) == tmp_path


def test_github_url_and_subpath(monkeypatch):
    seen = []
    monkeypatch.setattr(sources, "_download", lambda url, token, restricted: seen.append(url) or make_zip(
        {"repo-main/sub/skills/a/SKILL.md": "x"}))
    root = sources.resolve("https://github.com/o/r/tree/dev/sub")
    assert seen == ["https://codeload.github.com/o/r/zip/refs/heads/dev"]
    assert (root / "skills/a/SKILL.md").exists()


def test_cache_hit_skips_download(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "_download", lambda u, t, r: calls.append(u) or make_zip({"r/a.txt": "x"}))
    sources.resolve("https://github.com/o/r")
    sources.resolve("https://github.com/o/r")
    assert len(calls) == 1
    sources.resolve("https://github.com/o/r", force=True)
    assert len(calls) == 2


def test_public_mode_blocks_local_and_foreign_hosts(tmp_path):
    with pytest.raises(ValueError):
        sources.resolve(str(tmp_path))
    with pytest.raises(ValueError):
        sources.resolve("https://169.254.169.254/latest/a.zip")


def test_cache_is_scoped_per_token(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "_download", lambda u, t, r: calls.append(t) or make_zip({"r/a.txt": "x"}))
    sources.resolve("https://github.com/o/r", token="A")
    sources.resolve("https://github.com/o/r", token="B")
    sources.resolve("https://github.com/o/r", token="A")
    assert calls == ["A", "B"]


def test_rejects_http_and_non_zip():
    with pytest.raises(ValueError):
        sources.resolve("http://example.com/a.zip")
    with pytest.raises(ValueError):
        sources.resolve("https://github.com/page.txt")


def test_zip_slip(monkeypatch):
    monkeypatch.setattr(sources, "_download", lambda u, t, r: make_zip({"../evil.txt": "x"}))
    with pytest.raises(ValueError):
        sources.resolve("https://github.com/o/r/archive/a.zip")
