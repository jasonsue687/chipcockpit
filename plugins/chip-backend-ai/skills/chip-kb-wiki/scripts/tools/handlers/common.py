"""Shared utilities for handlers and entry scripts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SHA_PREFIX_LEN = 12


@dataclass(frozen=True)
class FileMeta:
    sha: str
    size: int
    mtime: str
    type: str
    name: str
    path: Path


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the repo root (first ancestor with a pyproject.toml).

    Search order when start is None:
      1. cwd and its ancestors  — works when the scripts are bundled outside
         the target repo (e.g. shipped inside a Claude Code plugin/skill).
      2. this file's ancestors  — works when the package lives inside the
         target repo (the original chip-knowledge-ai layout).

    Pass start explicitly to constrain the search to one starting point.
    """
    if start is not None:
        roots = [start.resolve()]
    else:
        roots = [Path.cwd().resolve(), Path(__file__).resolve()]
    seen: set[Path] = set()
    for root in roots:
        for candidate in [root, *root.parents]:
            if candidate in seen:
                continue
            seen.add(candidate)
            if (candidate / "pyproject.toml").is_file():
                return candidate
    raise RuntimeError(
        "Could not locate repo root (no pyproject.toml found upward from cwd "
        "or from the scripts package). Run scripts/bootstrap.sh first, or "
        "drop a pyproject.toml at your repo root."
    )


def compute_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:SHA_PREFIX_LEN]


def file_meta(path: Path) -> FileMeta:
    p = path.resolve()
    stat = p.stat()
    ext = p.suffix.lower().lstrip(".")
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    return FileMeta(
        sha=compute_sha(p),
        size=stat.st_size,
        mtime=mtime,
        type=ext,
        name=p.name,
        path=p,
    )


def human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(n)
    for unit in units:
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


_SLUG_BAD = re.compile(r"[\s/\\?<>:*|\"#%&{}$!'@+`=]+")


def slugify(text: str, max_len: int = 60) -> str:
    cleaned = _SLUG_BAD.sub("-", text.strip()).strip("-.")
    if not cleaned:
        cleaned = "x"
    return cleaned[:max_len]


PARSED_ROOT_NAME = "parsed"


def parsed_dir(repo_root: Path, source_path: Path) -> Path:
    """Return the per-source dir under parsed/ (named after the slugified source filename)."""
    raw_root = repo_root / "raw"
    try:
        rel = source_path.resolve().relative_to(raw_root.resolve())
    except ValueError:
        rel = Path(source_path.name)
    slug = slugify(str(rel))
    return repo_root / PARSED_ROOT_NAME / slug


def parsed_path(repo_root: Path, source_path: Path, slug: str) -> Path:
    return parsed_dir(repo_root, source_path) / f"{slug}.md"


def parsed_meta_path(repo_root: Path, source_path: Path) -> Path:
    return parsed_dir(repo_root, source_path) / "_meta.json"


def write_md(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


SUPPORTED_EXTS = {"docx", "xlsx", "pptx"}


def is_supported(path: Path) -> bool:
    return path.suffix.lower().lstrip(".") in SUPPORTED_EXTS
