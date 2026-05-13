from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import DEFAULT_CONFIG, DEFAULT_STATE, save_config, save_state

BEGIN_MARKER = "<!-- lateral-mode:begin -->"
END_MARKER = "<!-- lateral-mode:end -->"


HOOK_WRAPPER = """#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

SOURCE_ROOT = "__LATERAL_SOURCE_ROOT__"
if SOURCE_ROOT:
    sys.path.insert(0, SOURCE_ROOT)

PROJECT_MODE = "__LATERAL_PROJECT_MODE__"


def main() -> None:
    if PROJECT_MODE == "cwd":
        repo_root = Path.cwd()
    else:
        repo_root = Path(__file__).resolve().parents[2]
    args = ["lateral", "hook", *sys.argv[1:], "--project", str(repo_root)]
    try:
        from lateral.cli import main as lateral_main
    except ModuleNotFoundError:
        exe = shutil.which("lateral")
        if not exe:
            print("lateral command is not installed or not on PATH", file=sys.stderr)
            sys.exit(2)
        os.execvp(exe, args)
    sys.argv = args
    lateral_main()


if __name__ == "__main__":
    main()
"""

AGENTS_BLOCK = """# Lateral mode policy

Use direct mode for obvious, localized, mechanical changes.
Use lateral mode for ambiguous debugging, intermittent failures, architecture decisions,
root-cause analysis, incident response, or after repeated failed attempts.

When lateral mode is active:
1. Anchor the task before editing.
2. Generate 3-5 materially distinct hypotheses.
3. Give each hypothesis a cheap discriminating probe.
4. Prefer read-only evidence before implementation.
5. Converge before editing, or explain why the edit itself is the reversible probe.
6. End with validation or a concrete reason validation was not possible.

Control commands:
- `/lateral on`
- `/lateral off`
- `/lateral auto`
- `/lateral lite`
- `/lateral strict`
- `/lateral status`
"""

LATERAL_DEBUG_SKILL = """---
name: lateral-debug
description: Use for ambiguous, intermittent, cross-layer, flaky, or repeatedly failing bugs. Do not use for obvious localized fixes.
---

Before editing:
1. Anchor the problem: symptoms, known facts, unknowns, success criteria, risk constraints.
2. Generate 3-5 materially distinct hypotheses.
3. Each hypothesis must include id, frame, mechanism_class, layer, first_probe, confirm_signal, falsify_signal, cost, and risk.
4. Run or propose the cheapest read-only probe per hypothesis.
5. Rank the top 2 by evidence, discriminative power, feasibility, reversibility, and validation clarity.
6. Record convergence with:

```bash
lateral checkpoint --json '{"anchor":{"problem":"...","success_criteria":["..."]},"hypotheses":[{"id":"H1","mechanism_class":"...","layer":"...","first_probe":"..."},{"id":"H2","mechanism_class":"...","layer":"...","first_probe":"..."}],"winner":"H1"}'
```
"""

LATERAL_DESIGN_SKILL = """---
name: lateral-design
description: Use for architecture, API design, naming, refactor strategy, or feature planning with real tradeoffs.
---

Before implementation:
1. Anchor constraints and success criteria.
2. Produce 3-5 design frames that differ by mechanism, ownership boundary, rollout shape, or failure mode.
3. Compare correctness, complexity, rollout, reversibility, observability, security, and validation.
4. Recommend a path and record the chosen frame with `lateral checkpoint --json ...`.
"""

CLAUDE_REFRAMER = """---
name: reframer
description: Generates materially distinct frames and probes for ambiguous debugging or design tasks.
disallowedTools: Write, Edit, MultiEdit
---

Stay read-only. Generate distinct causal or design frames. Every frame must imply a different first probe or falsifier.
"""

CLAUDE_VERIFIER = """---
name: verifier
description: Designs cheap probes and validation commands for the winning hypothesis.
disallowedTools: Write, Edit, MultiEdit
---

Design probes and validation plans. Prefer tests, logs, targeted reads, grep, and reproducible commands.
"""

CODEX_REFRAMER = """name = "reframer"
description = "Read-only agent that generates materially distinct hypotheses and probes before edits."
sandbox_mode = "read-only"
model_reasoning_effort = "medium"
developer_instructions = '''
Stay read-only. Generate 3-5 distinct frames.
Each frame must differ by mechanism, layer, first probe, or falsifier.
Do not edit code. Return top 2 hypotheses.
'''
"""

CODEX_VERIFIER = """name = "verifier"
description = "Read-only agent that designs probes and validation commands."
sandbox_mode = "read-only"
model_reasoning_effort = "medium"
developer_instructions = '''
Design the cheapest discriminating probe for each hypothesis.
Prefer tests, grep, logs, schema inspection, and targeted repros.
Do not edit code.
'''
"""

CODEX_IMPLEMENTER = """name = "implementer"
description = "Implementation agent for minimal reversible changes after convergence."
model_reasoning_effort = "medium"
developer_instructions = '''
Implement only after the parent has selected a winning hypothesis.
Make the smallest reversible change. Run validation.
'''
"""

LATERAL_CONTROL_SKILL = """---
name: lateral-control
description: Control and inspect Lateral Mode. Use when the user asks to enable, disable, inspect, reset, or measure lateral mode.
argument-hint: "on | off | auto | lite | strict | status | metrics | report"
disable-model-invocation: true
---

Use the local command:

```bash
lateral-mode status
lateral-mode on
lateral-mode off
lateral-mode auto
lateral-mode lite
lateral-mode strict
lateral-mode reset
lateral-mode metrics
lateral-mode report
```
"""

CLAUDE_PLUGIN_HOOK_SCRIPT = """#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def plugin_root() -> Path:
    return Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1]).resolve()


def plugin_data() -> Path:
    return Path(os.environ.get("CLAUDE_PLUGIN_DATA") or (Path.home() / ".lateral-mode-plugin")).resolve()


def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()


def has_option(args: list[str], name: str) -> bool:
    return any(arg == name or arg.startswith(f"{name}=") for arg in args)


def bootstrap() -> None:
    root = plugin_root()
    sys.path.insert(0, str(root / "vendor"))
    data = plugin_data()
    os.environ["LATERAL_HOME"] = str(data)

    from lateral.core import DEFAULT_CONFIG, DEFAULT_STATE, save_json

    lateral_dir = data / ".lateral"
    config_path = lateral_dir / "config.json"
    state_path = lateral_dir / "state.json"
    if not config_path.exists():
        config = dict(DEFAULT_CONFIG)
        config.update({"enabled": True, "mode": "auto", "last_enabled_mode": "auto", "targets": ["claude"]})
        save_json(config_path, config)
    if not state_path.exists():
        save_json(state_path, dict(DEFAULT_STATE))


def main() -> None:
    bootstrap()
    from lateral.cli import main as lateral_main

    args = sys.argv[1:]
    if not has_option(args, "--project"):
        args.extend(["--project", str(project_dir())])
    if not has_option(args, "--platform"):
        args.extend(["--platform", "claude"])
    sys.argv = ["lateral", "hook", *args]
    lateral_main()


if __name__ == "__main__":
    main()
"""

CLAUDE_PLUGIN_BIN = """#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


PATH_COMMANDS = {
    "on",
    "off",
    "mode",
    "auto",
    "lite",
    "strict",
    "status",
    "metrics",
    "report",
    "outcome",
    "doctor",
    "reset",
    "checkpoint",
}


def plugin_root() -> Path:
    return Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[1]).resolve()


def plugin_data() -> Path:
    return Path(os.environ.get("CLAUDE_PLUGIN_DATA") or (Path.home() / ".lateral-mode-plugin")).resolve()


def project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()


def has_path(args: list[str]) -> bool:
    return any(arg == "--path" or arg.startswith("--path=") for arg in args)


def bootstrap() -> None:
    root = plugin_root()
    sys.path.insert(0, str(root / "vendor"))
    data = plugin_data()
    os.environ["LATERAL_HOME"] = str(data)

    from lateral.core import DEFAULT_CONFIG, DEFAULT_STATE, save_json

    lateral_dir = data / ".lateral"
    config_path = lateral_dir / "config.json"
    state_path = lateral_dir / "state.json"
    if not config_path.exists():
        config = dict(DEFAULT_CONFIG)
        config.update({"enabled": True, "mode": "auto", "last_enabled_mode": "auto", "targets": ["claude"]})
        save_json(config_path, config)
    if not state_path.exists():
        save_json(state_path, dict(DEFAULT_STATE))


def main() -> None:
    bootstrap()
    from lateral.cli import main as lateral_main

    args = sys.argv[1:] or ["status"]
    if args[0] in {"auto", "lite", "strict"}:
        args = ["mode", args[0], *args[1:]]
    if args[0] in PATH_COMMANDS and not has_path(args):
        args.extend(["--path", str(project_dir())])
    sys.argv = ["lateral", *args]
    lateral_main()


if __name__ == "__main__":
    main()
"""

PLUGIN_README = """# lateral-mode

Claude Code plugin for the Lateral Mode MVP.

Run without installing:

```bash
claude --plugin-dir ./plugins/lateral-mode
```

Install from the local marketplace:

```bash
claude plugin marketplace add .
claude plugin install lateral-mode@lateral-local
```
"""

PLUGIN_CHANGELOG = """# Changelog

## 0.2.0 - 2026-05-13

### Added

- Added Claude Code plugin packaging.
- Added plugin-scoped hooks, skills, agents, binary, and vendored engine.
"""

PLUGIN_LICENSE = """MIT License

Copyright (c) 2026 local

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction.
"""


def claude_settings() -> dict[str, Any]:
    hook = 'python3 "$CLAUDE_PROJECT_DIR/.lateral/hooks/lateral_hook.py"'
    return {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": f"{hook} user-prompt --platform claude"}]}],
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|MultiEdit|Bash|WebSearch|WebFetch",
                    "hooks": [{"type": "command", "command": f"{hook} pre-tool --platform claude"}],
                }
            ],
            "Stop": [{"hooks": [{"type": "command", "command": f"{hook} stop --platform claude"}]}],
        }
    }


def codex_hooks() -> dict[str, Any]:
    root = 'ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd); python3 "$ROOT/.lateral/hooks/lateral_hook.py"'
    return {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": f"{root} user-prompt --platform codex"}]}],
            "PreToolUse": [
                {
                    "matcher": "Bash|apply_patch|Edit|Write|MultiEdit|mcp__.*",
                    "hooks": [{"type": "command", "command": f"{root} pre-tool --platform codex"}],
                }
            ],
            "Stop": [{"hooks": [{"type": "command", "command": f"{root} stop --platform codex", "timeout": 30}]}],
        }
    }


def plugin_manifest() -> dict[str, Any]:
    return {
        "name": "lateral-mode",
        "version": "0.1.0",
        "description": "Local lateral workflow gate for ambiguous coding tasks",
        "author": {"name": "local"},
        "license": "MIT",
        "keywords": ["lateral", "coding-agents", "verification"],
        "skills": "./skills/",
        "hooks": "./hooks.json",
        "interface": {
            "displayName": "Lateral Mode",
            "shortDescription": "Forces hypotheses, probes, and validation on ambiguous tasks.",
            "longDescription": "A local plugin-controlled MVP that keeps simple tasks direct and applies a lateral workflow gate to ambiguous debugging or design work.",
            "developerName": "local",
            "category": "Productivity",
            "capabilities": ["Interactive", "Write"],
            "defaultPrompt": [
                "Use lateral mode for this ambiguous bug.",
                "Show lateral status.",
                "Turn lateral mode off.",
            ],
            "brandColor": "#2563EB",
        },
    }


def marketplace() -> dict[str, Any]:
    return {
        "name": "local",
        "interface": {"displayName": "Local Plugins"},
        "plugins": [
            {
                "name": "lateral-mode",
                "source": {"source": "local", "path": "./plugins/lateral-mode"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        ],
    }


def installed_marketplace() -> dict[str, Any]:
    payload = marketplace()
    payload["plugins"][0]["policy"]["installation"] = "INSTALLED_BY_DEFAULT"
    return payload


def claude_plugin_manifest() -> dict[str, Any]:
    return {
        "name": "lateral-mode",
        "version": "0.2.0",
        "description": "Claude Code plugin that gates ambiguous coding tasks with lateral hypotheses, probes, and validation.",
        "author": {"name": "local"},
        "license": "MIT",
        "keywords": ["claude-code", "lateral-thinking", "debugging", "workflow", "validation"],
        "skills": "./skills/",
        "hooks": "./hooks/hooks.json",
    }


def claude_marketplace() -> dict[str, Any]:
    return {
        "name": "lateral-local",
        "metadata": {"description": "Local marketplace for the Lateral Mode Claude Code plugin."},
        "owner": {"name": "local"},
        "plugins": [
            {
                "name": "lateral-mode",
                "source": "./plugins/lateral-mode",
                "description": "Claude Code plugin that gates ambiguous coding tasks with lateral hypotheses, probes, and validation.",
                "version": "0.2.0",
                "author": {"name": "local"},
                "category": "development-workflows",
                "tags": ["claude-code", "debugging", "workflow", "validation"],
            }
        ],
    }


def claude_plugin_hooks() -> dict[str, Any]:
    command = "${CLAUDE_PLUGIN_ROOT}/scripts/lateral_hook.py"
    return {
        "description": "Lateral Mode prompt, tool, and stop gates for Claude Code.",
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": command, "args": ["user-prompt", "--platform", "claude"], "timeout": 30}]}
            ],
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|MultiEdit|Bash",
                    "hooks": [{"type": "command", "command": command, "args": ["pre-tool", "--platform", "claude"], "timeout": 30}],
                }
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": command, "args": ["stop", "--platform", "claude"], "timeout": 30}]}
            ],
        },
    }


def write_text(path: Path, content: str, force: bool, executable: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return False
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)
    return True


def write_json(path: Path, payload: dict[str, Any], force: bool) -> bool:
    return write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", force)


def upsert_marked_block(path: Path, block: str) -> None:
    wrapped = f"{BEGIN_MARKER}\n{block.rstrip()}\n{END_MARKER}\n"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(wrapped, encoding="utf-8")
        return
    current = path.read_text(encoding="utf-8")
    if BEGIN_MARKER in current and END_MARKER in current:
        before = current.split(BEGIN_MARKER, 1)[0]
        after = current.split(END_MARKER, 1)[1]
        path.write_text(before + wrapped + after.lstrip("\n"), encoding="utf-8")
        return
    path.write_text(current.rstrip() + "\n\n" + wrapped, encoding="utf-8")


def init_project(project: str | Path, target: str = "both", force: bool = False) -> list[str]:
    root = Path(project).resolve()
    changed: list[str] = []
    config = dict(DEFAULT_CONFIG)
    config.update({"enabled": False, "mode": "off", "last_enabled_mode": "auto"})

    if force or not (root / ".lateral" / "config.json").exists():
        save_config(root, config)
        changed.append(".lateral/config.json")
    if force or not (root / ".lateral" / "state.json").exists():
        save_state(root, dict(DEFAULT_STATE))
        changed.append(".lateral/state.json")

    hook_source = (
        HOOK_WRAPPER
        .replace("__LATERAL_SOURCE_ROOT__", str(Path(__file__).resolve().parents[1]))
        .replace("__LATERAL_PROJECT_MODE__", "local")
    )
    if write_text(root / ".lateral" / "hooks" / "lateral_hook.py", hook_source, force=True, executable=True):
        changed.append(".lateral/hooks/lateral_hook.py")

    if target in {"both", "codex"}:
        upsert_marked_block(root / "AGENTS.md", AGENTS_BLOCK)
        write_text(root / ".agents" / "skills" / "lateral-debug" / "SKILL.md", LATERAL_DEBUG_SKILL, force)
        write_text(root / ".agents" / "skills" / "lateral-design" / "SKILL.md", LATERAL_DESIGN_SKILL, force)
        write_text(root / ".codex" / "agents" / "reframer.toml", CODEX_REFRAMER, force)
        write_text(root / ".codex" / "agents" / "verifier.toml", CODEX_VERIFIER, force)
        write_text(root / ".codex" / "agents" / "implementer.toml", CODEX_IMPLEMENTER, force)
        write_json(root / ".codex" / "hooks.json", codex_hooks(), force)
        write_text(root / ".codex" / "config.toml", "[features]\ncodex_hooks = true\n", force)
        write_json(root / ".agents" / "plugins" / "marketplace.json", marketplace(), force)
        write_plugin_bundle(root, force)
        changed.extend(["AGENTS.md", ".agents/skills", ".codex", ".agents/plugins", "plugins/lateral-mode"])

    if target in {"both", "claude"}:
        upsert_marked_block(root / ".claude" / "CLAUDE.md", AGENTS_BLOCK)
        write_text(root / ".claude" / "skills" / "lateral-debug" / "SKILL.md", LATERAL_DEBUG_SKILL, force)
        write_text(root / ".claude" / "skills" / "lateral-design" / "SKILL.md", LATERAL_DESIGN_SKILL, force)
        write_text(root / ".claude" / "agents" / "reframer.md", CLAUDE_REFRAMER, force)
        write_text(root / ".claude" / "agents" / "verifier.md", CLAUDE_VERIFIER, force)
        write_json(root / ".claude" / "settings.json", claude_settings(), force)
        write_json(root / ".claude-plugin" / "marketplace.json", claude_marketplace(), force)
        write_claude_plugin_bundle(root, force)
        changed.extend([".claude", ".claude-plugin", "plugins/lateral-mode"])

    return changed


def install_global(home: str | Path, force: bool = False) -> list[str]:
    root = Path(home).resolve()
    changed: list[str] = []
    config = dict(DEFAULT_CONFIG)
    config.update({"enabled": True, "mode": "auto", "last_enabled_mode": "auto"})

    if force or not (root / ".lateral" / "config.json").exists():
        save_config(root, config)
        changed.append(".lateral/config.json")
    if force or not (root / ".lateral" / "state.json").exists():
        save_state(root, dict(DEFAULT_STATE))
        changed.append(".lateral/state.json")

    hook_source = (
        HOOK_WRAPPER
        .replace("__LATERAL_SOURCE_ROOT__", str(Path(__file__).resolve().parents[1]))
        .replace("__LATERAL_PROJECT_MODE__", "cwd")
    )
    if write_text(root / ".lateral" / "hooks" / "lateral_hook.py", hook_source, force=True, executable=True):
        changed.append(".lateral/hooks/lateral_hook.py")

    write_text(root / ".agents" / "skills" / "lateral-debug" / "SKILL.md", LATERAL_DEBUG_SKILL, force)
    write_text(root / ".agents" / "skills" / "lateral-design" / "SKILL.md", LATERAL_DESIGN_SKILL, force)
    write_json(root / ".agents" / "plugins" / "marketplace.json", installed_marketplace(), force)
    write_global_plugin_bundle(root, force)
    write_json(root / ".claude-plugin" / "marketplace.json", claude_marketplace(), force)
    write_claude_plugin_bundle(root, force)
    changed.extend([".agents/skills", ".agents/plugins", ".claude-plugin", "plugins/lateral-mode"])
    return changed


def write_plugin_bundle(root: Path, force: bool) -> None:
    plugin = root / "plugins" / "lateral-mode"
    write_json(plugin / ".codex-plugin" / "plugin.json", plugin_manifest(), force)
    write_json(plugin / "hooks.json", codex_hooks(), force)
    write_text(plugin / "skills" / "lateral-debug" / "SKILL.md", LATERAL_DEBUG_SKILL, force)
    write_text(plugin / "skills" / "lateral-design" / "SKILL.md", LATERAL_DESIGN_SKILL, force)


def write_global_plugin_bundle(root: Path, force: bool) -> None:
    plugin = root / "plugins" / "lateral-mode"
    hook = f'python3 "{root / ".lateral" / "hooks" / "lateral_hook.py"}"'
    hooks = {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": f"{hook} user-prompt --platform codex"}]}],
            "PreToolUse": [
                {
                    "matcher": "Bash|apply_patch|Edit|Write|MultiEdit|mcp__.*",
                    "hooks": [{"type": "command", "command": f"{hook} pre-tool --platform codex"}],
                }
            ],
            "Stop": [{"hooks": [{"type": "command", "command": f"{hook} stop --platform codex", "timeout": 30}]}],
        }
    }
    write_json(plugin / ".codex-plugin" / "plugin.json", plugin_manifest(), force)
    write_json(plugin / "hooks.json", hooks, force)
    write_text(plugin / "skills" / "lateral-debug" / "SKILL.md", LATERAL_DEBUG_SKILL, force)
    write_text(plugin / "skills" / "lateral-design" / "SKILL.md", LATERAL_DESIGN_SKILL, force)


def write_lateral_vendor(plugin: Path, force: bool) -> None:
    source = Path(__file__).resolve().parents[1] / "lateral"
    vendor = plugin / "vendor" / "lateral"
    for src in sorted(source.glob("*.py")):
        write_text(vendor / src.name, src.read_text(encoding="utf-8"), force=True)


def write_claude_plugin_bundle(root: Path, force: bool) -> None:
    plugin = root / "plugins" / "lateral-mode"
    write_json(plugin / ".claude-plugin" / "plugin.json", claude_plugin_manifest(), force)
    write_json(plugin / "hooks" / "hooks.json", claude_plugin_hooks(), force)
    write_text(plugin / "scripts" / "lateral_hook.py", CLAUDE_PLUGIN_HOOK_SCRIPT, force, executable=True)
    write_text(plugin / "bin" / "lateral-mode", CLAUDE_PLUGIN_BIN, force, executable=True)
    write_text(plugin / "skills" / "lateral-debug" / "SKILL.md", LATERAL_DEBUG_SKILL, force)
    write_text(plugin / "skills" / "lateral-design" / "SKILL.md", LATERAL_DESIGN_SKILL, force)
    write_text(plugin / "skills" / "lateral-control" / "SKILL.md", LATERAL_CONTROL_SKILL, force)
    write_text(plugin / "agents" / "reframer.md", CLAUDE_REFRAMER, force)
    write_text(plugin / "agents" / "verifier.md", CLAUDE_VERIFIER, force)
    write_text(plugin / "README.md", PLUGIN_README, force)
    write_text(plugin / "CHANGELOG.md", PLUGIN_CHANGELOG, force)
    write_text(plugin / "LICENSE", PLUGIN_LICENSE, force)
    write_lateral_vendor(plugin, force)
