"""Resolves a skills source (local folder, GitHub URL or .zip link) to a local directory."""
import hashlib
import io
import os
import re
import shutil
import time
import urllib.request
import zipfile
from urllib.parse import urlparse
from pathlib import Path

CACHE_DIR = Path(os.getenv("PROMPT_FORGE_CACHE", "~/.cache/prompt-forge")).expanduser()
TTL_SECONDS = 6 * 3600
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_FILES = 20_000
# Public deployments may only fetch from GitHub: blocks SSRF to internal hosts and local file reads.
ALLOWED_HOSTS = {"github.com", "codeload.github.com", "objects.githubusercontent.com", "raw.githubusercontent.com"}

_GITHUB = re.compile(r"^https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/tree/([^/]+)(?:/(.+))?)?/?$")


class _HostCheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https" or urlparse(newurl).hostname not in ALLOWED_HOSTS:
            raise ValueError("Redirect to a host that is not allowed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, token: str | None, restricted: bool) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "prompt-forge"})
    if token and urlparse(url).hostname in ALLOWED_HOSTS:
        req.add_header("Authorization", f"Bearer {token}")
    opener = urllib.request.build_opener(_HostCheckedRedirect) if restricted else urllib.request.build_opener()
    with opener.open(req, timeout=30) as resp:
        data = resp.read(MAX_ZIP_BYTES + 1)
    if len(data) > MAX_ZIP_BYTES:
        raise ValueError("Archive larger than 50 MB")
    return data


def _extract(data: bytes, dest: Path) -> None:
    tmp = dest.with_suffix(".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise ValueError("Archive too large once unpacked")
        for member in zf.infolist():  # zip-slip guard
            target = (tmp / member.filename).resolve()
            if not target.is_relative_to(tmp.resolve()):
                raise ValueError(f"Unsafe path in archive: {member.filename}")
        zf.extractall(tmp)
    entries = list(tmp.iterdir())
    root = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp  # GitHub wraps in one folder
    shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(root), dest)
    shutil.rmtree(tmp, ignore_errors=True)


def resolve(source: str, token: str | None = None, force: bool = False, local: bool = False) -> Path:
    """Local paths and non-GitHub hosts are only honoured when `local` is True (never on a public deployment).
    Remote sources are downloaded once and cached for TTL_SECONDS, separately per token so private repos
    are never served to someone else."""
    source = source.strip()
    if not source.startswith(("http://", "https://")):
        if not local:
            raise ValueError("Local folders are disabled on this deployment; use a GitHub URL")
        path = Path(source).expanduser()
        if not path.is_dir():
            raise FileNotFoundError(f"Not a folder: {path}")
        return path
    if not source.startswith("https://"):
        raise ValueError("Only https:// sources are allowed")
    if not local and urlparse(source).hostname not in ALLOWED_HOSTS:
        raise ValueError("Only github.com sources are allowed on this deployment")

    subpath = ""
    url = source
    if match := _GITHUB.match(source):
        owner, repo, branch, subpath = match.group(1), match.group(2), match.group(3), match.group(4) or ""
        ref = f"refs/heads/{branch}" if branch else "HEAD"
        url = f"https://codeload.github.com/{owner}/{repo}/zip/{ref}"
    elif not source.split("?")[0].endswith(".zip"):
        raise ValueError("Use a GitHub repository URL or a direct .zip link")
    if ".." in Path(subpath).parts:
        raise ValueError("Invalid subfolder")

    scope = hashlib.sha256((url + "|" + (token or "")).encode()).hexdigest()[:16]
    dest = CACHE_DIR / scope
    fresh = dest.is_dir() and time.time() - dest.stat().st_mtime < TTL_SECONDS
    if force or not fresh:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _extract(_download(url, token, not local), dest)
        os.utime(dest)
    root = dest / subpath if subpath else dest
    if not root.is_dir():
        raise FileNotFoundError(f"Subfolder '{subpath}' not found in {source}")
    return root
