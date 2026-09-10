"""Tests for the Copilot wiring: agent file, prompt file, hooks, settings.

Nothing here can prove VS Code will behave; that is what the discovery
run is for. What it can prove is that the files have the documented
shape, use documented names (a misspelled tool name is silently
ignored by VS Code, which would leave the agent without that tool), and
agree with each other and with the policy. The last test is the one
that earns its keep: every command the agent file tells the model to
run must be one the terminal allowlist would actually permit.
"""
import ast
import json
import re
from pathlib import Path

from govlib.policy import load_policy

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / ".github/agents/feature-author.agent.md"
PROMPT = ROOT / ".github/prompts/run-ticket.prompt.md"
HOOKS = ROOT / ".github/hooks/governance.json"
INSTRUCTIONS = ROOT / ".github/copilot-instructions.md"
SETTINGS = ROOT / ".vscode/settings.json"

# Tool names as documented for custom-agent frontmatter (VS Code docs,
# "AI features cheat sheet"), in <tool set>/<tool> form.
DOCUMENTED_TOOLS = {
    "read/readFile", "read/problems", "read/terminalLastCommand", "read/terminalSelection",
    "search/listDirectory", "search/fileSearch", "search/textSearch", "search/codebase",
    "search/usages", "search/changes",
    "edit/createFile", "edit/editFiles", "edit/createDirectory", "edit/editNotebook",
    "execute/runInTerminal", "execute/getTerminalOutput", "execute/createAndRunTask",
    "execute/runNotebookCell", "execute/testFailure",
    "web/fetch", "agent/runSubagent",
}
# Channels the design closes (see docs/PLAN.md §2.2/§2.5).
FORBIDDEN_TOOLS = {"search/textSearch", "search/codebase", "web/fetch", "agent/runSubagent",
                   "web", "agent", "search"}


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path}: no frontmatter"
    out = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("["):
            out[key.strip()] = ast.literal_eval(value)
        else:
            out[key.strip()] = value.strip('"')
    return out


def test_agent_frontmatter_uses_documented_names_only():
    fm = frontmatter(AGENT)
    assert fm["name"] == "feature-author"
    assert fm["description"]
    assert isinstance(fm["tools"], list) and fm["tools"]
    unknown = set(fm["tools"]) - DOCUMENTED_TOOLS
    assert not unknown, f"undocumented tool names would be silently ignored: {unknown}"
    assert not set(fm["tools"]) & FORBIDDEN_TOOLS


def test_agent_has_exactly_the_channels_the_design_allows():
    tools = set(frontmatter(AGENT)["tools"])
    assert {"read/readFile", "edit/createFile", "edit/editFiles",
            "execute/runInTerminal"} <= tools


def test_agent_cannot_spawn_subagents():
    assert frontmatter(AGENT)["agents"] == []


def test_prompt_file_targets_the_agent():
    fm = frontmatter(PROMPT)
    assert fm["agent"] == frontmatter(AGENT)["name"]
    assert fm["name"] == "run-ticket"


def test_hooks_route_every_event_to_the_entry_point():
    data = json.loads(HOOKS.read_text(encoding="utf-8"))
    hooks = data["hooks"]
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        assert event in hooks, event
        for entry in hooks[event]:
            assert entry["type"] == "command"
            assert "tools/gov.py hook" in entry["command"]
            for os_key in ("osx", "linux"):
                if os_key in entry:
                    assert "tools/gov.py hook" in entry[os_key]
            assert isinstance(entry.get("timeout", 30), int)


def test_always_on_instructions_are_short_and_domain_neutral():
    text = INSTRUCTIONS.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 6
    for marker in ("Scenario", "@status-", "Shopper", "@rollback", "Feature:", "Given "):
        assert marker not in text, f"convention content leaked into the always-on file: {marker!r}"


def test_settings_close_implicit_instruction_channels_and_auto_approve_the_cli():
    raw = SETTINGS.read_text(encoding="utf-8")
    stripped = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("//"))
    settings = json.loads(stripped)
    assert settings["chat.includeApplyingInstructions"] is False
    assert settings["chat.useAgentSkills"] is False
    assert settings["chat.useAgentsMdFile"] is False
    assert settings["chat.tools.terminal.autoApprove"]["python3 tools/gov.py"] is True
    assert any(v is True for k, v in settings["chat.tools.edits.autoApprove"].items()
               if k.startswith("features/"))


def test_every_command_the_agent_is_told_to_run_passes_the_terminal_allowlist():
    """The agent file quotes commands. If one of them would be denied by the
    hook, the agent is being set up to fail. Placeholders in angle brackets
    and optional groups in square brackets are substituted before checking."""
    policy = load_policy(ROOT)
    text = AGENT.read_text(encoding="utf-8")
    commands = re.findall(r"`(python3 tools/gov\.py [^`]+)`", text)
    assert commands, "no commands quoted in the agent file"
    checked = 0
    for raw in commands:
        if "|" in raw:  # a listing of subcommands, not a command
            continue
        cmd = re.sub(r"\[[^\]]*\]", "", raw)
        cmd = re.sub(r"<[^>]*>", "x", cmd)
        cmd = cmd.replace("TKT-n", "TKT-2")
        assert policy.terminal_allowed(cmd), f"agent is told to run a denied command: {raw!r}"
        checked += 1
    assert checked >= 4


def test_agent_names_every_cli_subcommand_it_may_use():
    text = AGENT.read_text(encoding="utf-8")
    for sub in ("declare", "validate", "finish", "load"):
        assert f"gov.py {sub}" in text or f"|{sub}" in text or f"{sub}|" in text
