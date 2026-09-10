"""Run directories, the manifest, the current-run pointer and the event log.

A run is `runs/<run_id>/`. Every hook invocation is a separate process,
so all state lives on disk: `manifest.json` for structured state,
`events.jsonl` for the append-only record of everything that happened.
`runs/.current` names the active run; `runs/.last` names the most recent
one, active or not, so a Stop hook can still find where to put a
transcript after `finish` has cleared the pointer.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_SCHEMA = "gov-run-manifest/1"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def runs_dir(repo_root: Path) -> Path:
    return repo_root / "runs"


def _pointer(repo_root: Path, name: str) -> Path:
    return runs_dir(repo_root) / name


@dataclass
class Run:
    root: Path
    manifest: dict

    # -- identity ---------------------------------------------------------
    @property
    def id(self) -> str:
        return self.manifest["run_id"]

    @property
    def ticket_id(self) -> str | None:
        return self.manifest.get("ticket_id")

    @property
    def status(self) -> str:
        return self.manifest.get("status", "started")

    @property
    def active(self) -> bool:
        return self.status != "finished"

    @property
    def declared(self) -> bool:
        return bool(self.manifest.get("classification"))

    @property
    def domains(self) -> tuple[str, ...]:
        c = self.manifest.get("classification") or {}
        return tuple(c.get("domains", ()))

    @property
    def allowed_write_globs(self) -> tuple[str, ...]:
        return tuple(self.manifest.get("allowed_write_globs", ()))

    # -- files ------------------------------------------------------------
    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    def save(self) -> None:
        self.manifest["updated_at"] = utcnow()
        self.manifest_path.write_text(
            json.dumps(self.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def log(self, event: str, **fields) -> dict:
        record = {"at": utcnow(), "event": event, **fields}
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def events(self) -> list[dict]:
        if not self.events_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def subdir(self, name: str) -> Path:
        p = self.root / name
        p.mkdir(parents=True, exist_ok=True)
        return p


def new_run(repo_root: Path, ticket_id: str | None, session_id: str | None, created_by: str) -> Run:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    suffix = secrets.token_hex(3)
    run_id = f"{stamp}_{ticket_id or 'no-ticket'}_{suffix}"
    root = runs_dir(repo_root) / run_id
    root.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "run_id": run_id,
        "ticket_id": ticket_id,
        "session_id": session_id,
        "created_at": utcnow(),
        "created_by": created_by,
        "status": "started",
        "hooks_active": created_by.startswith("hook:"),
        "baseline": None,
        "classification": None,
        "allowed_write_globs": [],
        "conventions_served": [],
        "validations": [],
        "prompts": [],
        "notes": [],
        "finished_at": None,
    }
    run = Run(root=root, manifest=manifest)
    run.save()
    _pointer(repo_root, ".current").write_text(run_id + "\n", encoding="utf-8")
    _pointer(repo_root, ".last").write_text(run_id + "\n", encoding="utf-8")
    run.log("run_created", run_id=run_id, ticket_id=ticket_id, created_by=created_by)
    return run


def load_run(repo_root: Path, run_id: str) -> Run:
    root = runs_dir(repo_root) / run_id
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return Run(root=root, manifest=manifest)


def _run_from_pointer(repo_root: Path, name: str) -> Run | None:
    p = _pointer(repo_root, name)
    if not p.exists():
        return None
    run_id = p.read_text(encoding="utf-8").strip()
    if not run_id or not (runs_dir(repo_root) / run_id / "manifest.json").exists():
        return None
    return load_run(repo_root, run_id)


def current_run(repo_root: Path) -> Run | None:
    """The active run, or None. A finished run is never 'current'."""
    run = _run_from_pointer(repo_root, ".current")
    if run is None or not run.active:
        return None
    return run


def last_run(repo_root: Path) -> Run | None:
    return _run_from_pointer(repo_root, ".last")


def clear_current(repo_root: Path) -> None:
    p = _pointer(repo_root, ".current")
    if p.exists():
        p.unlink()


def list_runs(repo_root: Path) -> list[Run]:
    out: list[Run] = []
    base = runs_dir(repo_root)
    if not base.exists():
        return out
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / "manifest.json").exists():
            out.append(load_run(repo_root, d.name))
    return out
