from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .core import (
    DEFAULT_STATE,
    append_event,
    apply_checkpoint,
    build_lateral_context,
    can_stop,
    can_write,
    compute_metrics,
    compute_workspace_metrics,
    is_risky_bash,
    is_write_tool,
    load_eval_fixtures,
    load_effective_config,
    load_effective_state,
    run_classifier_eval,
    run_eval_suite,
    save_effective_config,
    save_effective_state,
    update_state_from_prompt,
)
from .installer import init_project, install_global


def configure_mode(project: Path, mode: str) -> dict[str, Any]:
    config = load_effective_config(project)
    if mode == "off":
        config["enabled"] = False
        config["mode"] = "off"
    else:
        config["enabled"] = True
        config["mode"] = mode
        config["last_enabled_mode"] = mode
    save_effective_config(project, config)
    return config


def command_on(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    config = load_effective_config(project)
    mode = config.get("last_enabled_mode") or "auto"
    if mode == "off":
        mode = "auto"
    config["enabled"] = True
    config["mode"] = mode
    save_effective_config(project, config)
    print(f"lateral enabled ({mode})")


def command_off(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    config = load_effective_config(project)
    if config.get("mode") != "off":
        config["last_enabled_mode"] = config.get("mode", "auto")
    config["enabled"] = False
    config["mode"] = "off"
    save_effective_config(project, config)
    print("lateral disabled")


def command_mode(args: argparse.Namespace) -> None:
    config = configure_mode(Path(args.path).resolve(), args.mode)
    print(f"lateral mode: {config['mode']}")


def command_status(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    config = load_effective_config(project)
    state = load_effective_state(project)
    print(json.dumps({"config": config, "state": state}, indent=2, sort_keys=True))


def command_metrics(args: argparse.Namespace) -> None:
    print(json.dumps(compute_metrics(Path(args.path).resolve()), indent=2, sort_keys=True))


def build_report(project: Path) -> dict[str, Any]:
    config = load_effective_config(project)
    state = load_effective_state(project)
    metrics = compute_metrics(project)
    assessment = "unmeasured" if int(metrics["outcomes"]) == 0 else "measured"
    return {
        "workspace": str(project.resolve()),
        "config": {"enabled": bool(config.get("enabled")), "mode": config.get("mode", "off")},
        "state": {
            "runtime_mode": state.get("runtime_mode"),
            "phase": state.get("phase"),
            "winner": state.get("winner"),
            "validation": state.get("validation", {}),
        },
        "metrics": metrics,
        "workspaces": compute_workspace_metrics(project),
        "assessment": assessment,
    }


def command_report(args: argparse.Namespace) -> None:
    report = build_report(Path(args.path).resolve())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    metrics = report["metrics"]
    config = report["config"]
    print("Lateral Mode Report")
    print(f"Workspace: {report['workspace']}")
    print(f"Mode: {'enabled' if config['enabled'] else 'disabled'} {config['mode']}")
    print(f"Prompts: {metrics['user_prompts']}")
    print(f"Activation rate: {metrics['activation_rate']:.2f}")
    print(f"Strict activation rate: {metrics['strict_activation_rate']:.2f}")
    print(f"Pre-tool denies: {metrics['pre_tool_denies']}")
    print(f"Stop blocks: {metrics['stop_blocks']}")
    print(f"Outcomes: {metrics['outcomes']}")
    print(f"Resolve rate: {metrics['resolve_rate']:.2f}")
    print(f"Average rating: {metrics['average_rating']:.2f}")
    print(f"Assessment: {report['assessment']}")


def command_outcome(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    state = load_effective_state(project)
    rating = int(args.rating) if args.rating is not None else None
    append_event(
        project,
        "outcome",
        {
            "resolved": args.resolved == "yes",
            "rating": rating,
            "validation": args.validation,
            "runtime_mode": state.get("runtime_mode"),
            "winner": state.get("winner"),
            "notes": args.notes or "",
        },
    )
    print(json.dumps({"recorded": True, "resolved": args.resolved == "yes", "rating": rating}, sort_keys=True))


def command_doctor(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    checks = {
        ".lateral/config.json": (project / ".lateral" / "config.json").exists(),
        ".lateral/state.json": (project / ".lateral" / "state.json").exists(),
        ".lateral/hooks/lateral_hook.py": (project / ".lateral" / "hooks" / "lateral_hook.py").exists(),
        "AGENTS.md": (project / "AGENTS.md").exists(),
        ".claude/settings.json": (project / ".claude" / "settings.json").exists(),
        ".codex/hooks.json": (project / ".codex" / "hooks.json").exists(),
    }
    for name, ok in checks.items():
        print(f"{'ok' if ok else 'missing'} {name}")
    if args.strict and checks[".lateral/hooks/lateral_hook.py"]:
        proc = subprocess.run(
            [sys.executable, str(project / ".lateral" / "hooks" / "lateral_hook.py"), "user-prompt"],
            input='{"prompt":"/lateral status"}',
            text=True,
            cwd=project,
            capture_output=True,
        )
        hook_ok = proc.returncode == 0 and "lateral mode status" in proc.stdout.lower()
        print(f"{'ok' if hook_ok else 'failed'} hook_smoke")
        checks["hook_smoke"] = hook_ok
    if not all(checks.values()):
        sys.exit(1)


def command_reset(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    save_effective_state(project, dict(DEFAULT_STATE))
    print("lateral state reset")


def load_checkpoint_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.json:
        return json.loads(args.json)
    if args.file:
        return json.loads(Path(args.file).read_text(encoding="utf-8"))
    if args.stdin:
        return json.load(sys.stdin)
    raise SystemExit("checkpoint requires --json, --file, or --stdin")


def command_checkpoint(args: argparse.Namespace) -> None:
    project = Path(args.path).resolve()
    payload = load_checkpoint_payload(args)
    state = apply_checkpoint(load_effective_state(project), payload)
    save_effective_state(project, state)
    ok, reason = can_write(state)
    print(json.dumps({"phase": state.get("phase"), "winner": state.get("winner"), "can_write": ok, "reason": reason}, indent=2))


def command_eval(args: argparse.Namespace) -> None:
    fixtures = load_eval_fixtures(args.fixtures) if args.fixtures else None
    result = run_classifier_eval(args.mode, fixtures)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["passed"] != result["total"]:
        sys.exit(1)


def command_eval_suite(args: argparse.Namespace) -> None:
    result = run_eval_suite(args.fixtures, args.mode)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["suite_passed"] != result["suite_total"]:
        sys.exit(1)


def apply_prompt_control(project: Path, prompt: str) -> str | None:
    text = prompt.strip().lower()
    aliases = {
        "/lateral on": "on",
        "lateral on": "on",
        "/lateral off": "off",
        "lateral off": "off",
        "/lateral auto": "auto",
        "lateral auto": "auto",
        "/lateral lite": "lite",
        "lateral lite": "lite",
        "/lateral strict": "strict",
        "lateral strict": "strict",
        "/lateral status": "status",
        "lateral status": "status",
    }
    command = aliases.get(text)
    if command is None:
        return None

    config = load_effective_config(project)
    if command == "status":
        enabled = "enabled" if config.get("enabled") else "disabled"
        return f"Lateral mode status: {enabled}, mode={config.get('mode', 'off')}."
    if command == "off":
        if config.get("mode") != "off":
            config["last_enabled_mode"] = config.get("mode", "auto")
        config["enabled"] = False
        config["mode"] = "off"
        save_effective_config(project, config)
        return "Lateral mode disabled."
    if command == "on":
        mode = config.get("last_enabled_mode") or "auto"
        if mode == "off":
            mode = "auto"
    else:
        mode = command
    config["enabled"] = True
    config["mode"] = mode
    config["last_enabled_mode"] = mode
    save_effective_config(project, config)
    return f"Lateral mode enabled: {mode}."


def hook_output(payload: dict[str, Any] | None) -> None:
    if payload:
        print(json.dumps(payload))


def command_hook(args: argparse.Namespace) -> None:
    project = Path(args.project or ".").resolve()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    if args.event == "user-prompt":
        prompt = payload.get("prompt") or payload.get("input") or payload.get("message") or ""
        control_message = apply_prompt_control(project, prompt)
        if control_message is not None:
            append_event(project, "control", {"message": control_message})
            hook_output(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": control_message,
                    }
                }
            )
            return
        state, classification = update_state_from_prompt(project, prompt)
        runtime_mode = state.get("runtime_mode")
        append_event(
            project,
            "user_prompt",
            {
                "runtime_mode": runtime_mode,
                "configured_mode": state.get("configured_mode"),
                "score": classification.score,
                "reasons": classification.reasons,
                "negative_reasons": classification.negative_reasons,
            },
        )
        if runtime_mode not in {"off", "direct"}:
            hook_output(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": build_lateral_context(runtime_mode, classification),
                    }
                }
            )
        return

    state = load_effective_state(project)
    if args.event == "pre-tool":
        tool = payload.get("tool_name") or payload.get("toolName") or payload.get("name")
        tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
        command = str(tool_input.get("command") or tool_input.get("cmd") or "")

        if tool == "Bash" and is_risky_bash(command):
            append_event(project, "pre_tool", {"tool": tool, "decision": "deny", "reason": "risky_bash"})
            hook_output(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "Blocked risky Bash command.",
                    }
                }
            )
            return

        if state.get("runtime_mode") == "lateral_strict" and is_write_tool(tool):
            ok, reason = can_write(state)
            if not ok:
                append_event(project, "pre_tool", {"tool": tool, "decision": "deny", "reason": reason})
                hook_output(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": f"Lateral strict gate: {reason}. Run lateral-debug/design and record a checkpoint first.",
                        }
                    }
                )
                return
        append_event(project, "pre_tool", {"tool": tool, "decision": "allow"})
        return

    if args.event == "stop":
        if payload.get("stop_hook_active") is True:
            append_event(project, "stop", {"decision": "allow", "reason": "stop hook already active"})
            return
        ok, reason = can_stop(state)
        if not ok:
            append_event(project, "stop", {"decision": "block", "reason": reason})
            hook_output(
                {
                    "decision": "block",
                    "reason": (
                        "Before stopping, report validation or explain why validation was not possible. "
                        f"Lateral closure missing: {reason}."
                    ),
                }
            )
            return
        append_event(project, "stop", {"decision": "allow", "reason": reason})
        return

    raise SystemExit(f"unknown hook event: {args.event}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lateral")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_path(p: argparse.ArgumentParser) -> None:
        p.add_argument("--path", default=".", help="Project path")

    init = sub.add_parser("init", help="Install local lateral controls into a project")
    add_path(init)
    init.add_argument("--target", choices=["both", "claude", "codex"], default="both")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=lambda args: print("\n".join(init_project(Path(args.path), args.target, args.force))))

    install_global_cmd = sub.add_parser("install-global", help="Install always-on home plugin controls")
    install_global_cmd.add_argument("--home", default=str(Path.home()), help="Home directory to install into")
    install_global_cmd.add_argument("--force", action="store_true")
    install_global_cmd.set_defaults(func=lambda args: print("\n".join(install_global(Path(args.home), args.force))))

    on = sub.add_parser("on", help="Enable lateral controls")
    add_path(on)
    on.set_defaults(func=command_on)

    off = sub.add_parser("off", help="Disable lateral controls")
    add_path(off)
    off.set_defaults(func=command_off)

    mode = sub.add_parser("mode", help="Set mode")
    add_path(mode)
    mode.add_argument("mode", choices=["auto", "lite", "strict", "eval", "off"])
    mode.set_defaults(func=command_mode)

    for alias in ("auto", "lite", "strict"):
        alias_parser = sub.add_parser(alias, help=f"Shortcut for `mode {alias}`")
        add_path(alias_parser)
        alias_parser.set_defaults(
            func=lambda args, alias=alias: command_mode(argparse.Namespace(path=args.path, mode=alias))
        )

    status = sub.add_parser("status", help="Print config and state")
    add_path(status)
    status.set_defaults(func=command_status)

    metrics = sub.add_parser("metrics", help="Print local/global telemetry metrics")
    add_path(metrics)
    metrics.set_defaults(func=command_metrics)

    report = sub.add_parser("report", help="Print a human or JSON lateral effectiveness report")
    add_path(report)
    report.add_argument("--json", action="store_true")
    report.set_defaults(func=command_report)

    outcome = sub.add_parser("outcome", help="Record real task outcome for measurement")
    add_path(outcome)
    outcome.add_argument("--resolved", choices=["yes", "no"], required=True)
    outcome.add_argument("--rating", type=int, choices=[1, 2, 3, 4, 5])
    outcome.add_argument("--validation", choices=["passed", "failed", "not_run", "not_applicable"], default="not_run")
    outcome.add_argument("--notes", default="")
    outcome.set_defaults(func=command_outcome)

    doctor = sub.add_parser("doctor", help="Check installed files")
    add_path(doctor)
    doctor.add_argument("--strict", action="store_true", help="Also execute a generated hook smoke test")
    doctor.set_defaults(func=command_doctor)

    reset = sub.add_parser("reset", help="Reset lateral state without changing enabled mode")
    add_path(reset)
    reset.set_defaults(func=command_reset)

    checkpoint = sub.add_parser("checkpoint", help="Record anchor/hypotheses/probes/winner")
    add_path(checkpoint)
    source = checkpoint.add_mutually_exclusive_group(required=True)
    source.add_argument("--json")
    source.add_argument("--file")
    source.add_argument("--stdin", action="store_true")
    checkpoint.set_defaults(func=command_checkpoint)

    eval_cmd = sub.add_parser("eval", help="Run built-in MVP classifier eval")
    eval_cmd.add_argument("--mode", choices=["auto", "lite", "strict", "eval"], default="auto")
    eval_cmd.add_argument("--fixtures", help="JSON fixture file with id/kind/prompt/expected entries")
    eval_cmd.set_defaults(func=command_eval)

    eval_suite = sub.add_parser("eval-suite", help="Run multiple fixture files and aggregate results")
    eval_suite.add_argument("--mode", choices=["auto", "lite", "strict", "eval"], default="auto")
    eval_suite.add_argument(
        "--fixtures",
        action="append",
        required=True,
        help="JSON fixture file. Repeat for multiple files.",
    )
    eval_suite.set_defaults(func=command_eval_suite)

    hook = sub.add_parser("hook", help="Internal hook entrypoint")
    hook.add_argument("event", choices=["user-prompt", "pre-tool", "stop"])
    hook.add_argument("--platform", choices=["claude", "codex"], default="codex")
    hook.add_argument("--project", default=None)
    hook.set_defaults(func=command_hook)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
