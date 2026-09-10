"""Reading hook input and writing hook output for VS Code agent hooks.

Two facts about the hook protocol drive this module. First, field
casing is not stable: the documentation shows snake_case
(`hook_event_name`, `tool_name`, `tool_input`) while hooks in the wild
have received camelCase (`hookEventName`, `toolName`, `toolInput`, VS
Code issue #293631). Top-level keys are normalised to snake_case on the
way in; `tool_input` is left as sent, since path extraction searches it
by key name in both spellings anyway. Second, a hook that crashes is
treated by VS Code as a non-blocking warning, which means "allow". The
entry point therefore never lets an exception escape; see gov.py.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, TextIO

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")

EVENTS = (
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "Stop", "SubagentStart", "SubagentStop", "PreCompact",
)


def snake(key: str) -> str:
    return _CAMEL_RE.sub("_", key).lower()


def read_input(stream: TextIO | None = None) -> dict[str, Any]:
    raw = (stream or sys.stdin).read()
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {"_raw": data}
    return {snake(k): v for k, v in data.items()}


def emit(obj: dict[str, Any], stream: TextIO | None = None) -> None:
    (stream or sys.stdout).write(json.dumps(obj) + "\n")
    (stream or sys.stdout).flush()


def pre_tool_allow(reason: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
    if reason:
        out["permissionDecisionReason"] = reason
    return {"hookSpecificOutput": out}


def pre_tool_deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def additional_context(event: str, text: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def stop_block(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "Stop", "decision": "block", "reason": reason}}


def nothing() -> dict[str, Any]:
    return {}
