"""The scope policy: which paths belong to which domain, what is always
protected, what the agent may run in the terminal.

Read from policy.json at the repository root so a consuming team can map
its own layout onto the three domains without touching code. The glob
dialect is deliberately small: '**' spans directories, '*' does not,
and there is nothing else.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


class PolicyError(ValueError):
    """policy.json is missing or malformed."""


def glob_to_regex(glob: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(glob):
        ch = glob[i]
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
            if i < len(glob) and glob[i] == "/":
                i += 1
                out[-1] = "(?:.*/)?"
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$")


@dataclass(frozen=True)
class Policy:
    domains: tuple[str, ...]
    write_scope: dict[str, tuple[str, ...]]
    domain_paths: tuple[tuple[str, str], ...]
    protected: tuple[str, ...]
    read_denied_during_run: tuple[str, ...]
    tools_denied_during_run: frozenset[str]
    terminal_allow: tuple[re.Pattern[str], ...]

    def matches_any(self, path: str, globs) -> bool:
        return any(glob_to_regex(g).match(path) for g in globs)

    def is_protected(self, path: str) -> bool:
        return self.matches_any(path, self.protected)

    def is_read_denied_during_run(self, path: str) -> bool:
        return self.matches_any(path, self.read_denied_during_run)

    def allowed_write_globs(self, domains) -> tuple[str, ...]:
        out: list[str] = []
        for d in domains:
            out.extend(self.write_scope.get(d, ()))
        return tuple(out)

    def in_write_scope(self, path: str, domains) -> bool:
        return self.matches_any(path, self.allowed_write_globs(domains))

    def domain_of(self, path: str) -> str | None:
        for glob, domain in self.domain_paths:
            if glob_to_regex(glob).match(path):
                return domain
        return None

    def terminal_allowed(self, command: str) -> bool:
        cmd = command.strip()
        return any(rx.match(cmd) for rx in self.terminal_allow)


def load_policy(repo_root: Path) -> Policy:
    path = repo_root / "policy.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"{path} not found") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"{path}: {exc}") from exc
    if data.get("version") != 1:
        raise PolicyError(f"{path}: unsupported version {data.get('version')!r}")
    try:
        return Policy(
            domains=tuple(data["domains"]),
            write_scope={k: tuple(v) for k, v in data["write_scope"].items()},
            domain_paths=tuple((e["glob"], e["domain"]) for e in data["domain_paths"]),
            protected=tuple(data["protected"]),
            read_denied_during_run=tuple(data["read_denied_during_run"]),
            tools_denied_during_run=frozenset(data["tools_denied_during_run"]),
            terminal_allow=tuple(re.compile(p) for p in data["terminal_allow"]),
        )
    except KeyError as exc:
        raise PolicyError(f"{path}: missing key {exc}") from exc
