"""Git facts for the detective layer.

The hook is preventive and can be switched off. What cannot be switched
off is the working tree: at the end of a run, `git status` says which
files changed, and every one of them either lies inside the declared
scope or is a violation. Files that were already dirty when the run
started are excluded, so a stale working tree cannot manufacture false
violations.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from govlib.runstate import utcnow


def _git(repo_root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, check=False
        ).stdout
    except FileNotFoundError:
        return ""


def head(repo_root: Path) -> str | None:
    out = _git(repo_root, "rev-parse", "HEAD").strip()
    return out or None


@dataclass(frozen=True)
class DirtyFile:
    status: str
    path: str

    @property
    def kind(self) -> str:
        return {"??": "untracked", "A": "added", "M": "modified", "D": "deleted",
                "R": "renamed"}.get(self.status.strip()[:1] if self.status != "??" else "??",
                                     self.status.strip())


def dirty_files(repo_root: Path) -> list[DirtyFile]:
    out: list[DirtyFile] = []
    text = _git(repo_root, "status", "--porcelain", "--untracked-files=all")
    for line in text.splitlines():
        if len(line) < 4:
            continue
        status, rest = line[:2], line[3:]
        path = rest.split(" -> ", 1)[-1].strip()
        out.append(DirtyFile(status=status, path=path))
    return out


def file_hash(repo_root: Path, rel: str) -> str | None:
    p = repo_root / rel
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def snapshot(repo_root: Path) -> dict:
    files = dirty_files(repo_root)
    return {
        "captured_at": utcnow(),
        "head": head(repo_root),
        "dirty": [
            {"status": f.status, "path": f.path, "sha256": file_hash(repo_root, f.path)}
            for f in files
        ],
    }


def diff_patch(repo_root: Path) -> str:
    return _git(repo_root, "diff", "HEAD", "--", ".")


def changes_since(repo_root: Path, baseline: dict | None) -> list[dict]:
    """Dirty files now that were not dirty with the same content at the
    baseline."""
    before = {d["path"]: d.get("sha256") for d in (baseline or {}).get("dirty", [])}
    out: list[dict] = []
    for f in dirty_files(repo_root):
        digest = file_hash(repo_root, f.path)
        if f.path in before and before[f.path] == digest:
            continue
        out.append({"status": f.status, "path": f.path, "sha256": digest})
    return out
