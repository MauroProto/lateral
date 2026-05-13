from __future__ import annotations

import json
import os
import re
import hashlib
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "0.1"

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "enabled": False,
    "mode": "off",
    "last_enabled_mode": "auto",
    "targets": ["claude", "codex"],
    "lite_threshold": 2,
    "strict_threshold": 4,
}

DEFAULT_STATE: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "runtime_mode": "direct",
    "configured_mode": "off",
    "phase": "idle",
    "activation": {"score": 0, "reasons": [], "negative_reasons": []},
    "anchor": None,
    "hypotheses": [],
    "probes": [],
    "evidence": [],
    "ranking": [],
    "winner": None,
    "validation": {"commands": [], "result": "pending", "reason_if_not_run": ""},
    "risks": [],
    "failed_attempts": 0,
    "updated_at": None,
}

POSITIVE_SIGNALS: dict[str, int] = {
    "lateral": 4,
    "hipotesis": 4,
    "hypothesis": 4,
    "root cause": 2,
    "causa raiz": 2,
    "ambiguo": 2,
    "ambigua": 2,
    "intermitente": 2,
    "flaky": 2,
    "a veces": 2,
    "sometimes": 2,
    "only for some": 2,
    "some accounts": 1,
    "sin repro": 3,
    "no repro": 3,
    "no logro reproducir": 3,
    "cannot reproduce": 3,
    "usuarios reportan": 2,
    "users report": 2,
    "desaparece": 2,
    "disappear": 2,
    "missing later": 2,
    "duplicados": 2,
    "duplicated": 2,
    "regression": 2,
    "after deploy": 2,
    "same code": 1,
    "staging fails": 3,
    "only staging": 3,
    "ci fails": 3,
    "local passes": 2,
    "retries": 2,
    "race": 1,
    "carrera": 2,
    "async": 1,
    "cross-layer": 2,
    "cross layer": 2,
    "multi-layer": 2,
    "varias capas": 2,
    "ui, api": 2,
    "worker": 1,
    "backend": 1,
    "server": 1,
    "servidor": 1,
    "modal": 1,
    "webhook": 2,
    "never arrives": 2,
    "marked paid": 2,
    "stale": 2,
    "cache": 1,
    "eventually": 1,
    "after saving": 1,
    "old schema": 2,
    "schema": 2,
    "session": 1,
    "cookie": 1,
    "after redirect": 2,
    "totals": 2,
    "differ": 2,
    "export": 1,
    "subset": 2,
    "accounts": 1,
    "disagree": 2,
    "mismatch": 2,
    "distinto": 2,
    "different": 1,
    "csv": 1,
    "arquitectura": 2,
    "architecture": 2,
    "api design": 2,
    "tradeoff": 1,
    "migration strategy": 2,
    "refactor": 2,
    "risky refactor": 2,
    "boundaries": 1,
    "rollback": 1,
    "observability": 1,
    "incidente": 2,
    "incident": 2,
    "what else could explain": 2,
    "repeated failed": 2,
    "fallo repetido": 2,
}

NEGATIVE_SIGNALS: dict[str, int] = {
    "typo": -3,
    "ortografia": -2,
    "formato": -2,
    "format": -2,
    "lint": -2,
    "prettier": -2,
    "copyedit": -3,
    "copy": -2,
    "grammar": -3,
    "spelling": -3,
    "wording": -2,
    "sample": -1,
    "title": -1,
    "docs": -1,
    "readme": -1,
    "no code": -3,
    "only": -1,
    "solo": -1,
    "renombrar": -2,
    "rename": -2,
    "single file": -1,
    "one file": -1,
    "mecanico": -2,
    "mechanical": -2,
}

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "apply_patch"}
RISKY_BASH_PATTERNS = [
    re.compile(r"rm\s+-rf\s+/"),
    re.compile(r"git\s+push\b.*--force"),
    re.compile(r"curl\b.*\|\s*(sh|bash)"),
    re.compile(r"wget\b.*\|\s*(sh|bash)"),
]


@dataclass(frozen=True)
class Classification:
    mode: str
    score: int
    reasons: list[str]
    negative_reasons: list[str]


def project_paths(project: str | Path) -> dict[str, Path]:
    root = Path(project).resolve()
    return {
        "root": root,
        "lateral": root / ".lateral",
        "config": root / ".lateral" / "config.json",
        "state": root / ".lateral" / "state.json",
    }


def lateral_home() -> Path:
    return Path(os.environ.get("LATERAL_HOME", Path.home())).resolve()


def workspace_key(project: str | Path) -> str:
    raw = str(Path(project).resolve()).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def global_paths(project: str | Path) -> dict[str, Path]:
    root = lateral_home() / ".lateral"
    key = workspace_key(project)
    return {
        "root": Path(project).resolve(),
        "lateral": root,
        "config": root / "config.json",
        "state": root / "workspaces" / key / "state.json",
        "events": root / "events.jsonl",
    }


def effective_paths(project: str | Path) -> dict[str, Path]:
    local = project_paths(project)
    if local["config"].exists():
        return {**local, "events": local["lateral"] / "events.jsonl"}
    global_config = global_paths(project)["config"]
    if global_config.exists():
        return global_paths(project)
    return {**local, "events": local["lateral"] / "events.jsonl"}


def load_json(path: str | Path, default: dict[str, Any]) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return json.loads(json.dumps(default))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = json.loads(json.dumps(default))
        if "runtime_mode" in data:
            data["runtime_mode"] = "lateral_strict"
            data["phase"] = "blocked"
            data["risks"] = ["state_file_corrupt"]
    merged = json.loads(json.dumps(default))
    merged.update(data)
    return merged


def save_json(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_at"] = int(time.time())
    fd, tmp = tempfile.mkstemp(prefix=p.name, dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_config(project: str | Path) -> dict[str, Any]:
    return load_json(project_paths(project)["config"], DEFAULT_CONFIG)


def save_config(project: str | Path, config: dict[str, Any]) -> None:
    save_json(project_paths(project)["config"], config)


def load_state(project: str | Path) -> dict[str, Any]:
    return load_json(project_paths(project)["state"], DEFAULT_STATE)


def save_state(project: str | Path, state: dict[str, Any]) -> None:
    save_json(project_paths(project)["state"], state)


def load_effective_config(project: str | Path) -> dict[str, Any]:
    return load_json(effective_paths(project)["config"], DEFAULT_CONFIG)


def save_effective_config(project: str | Path, config: dict[str, Any]) -> None:
    save_json(effective_paths(project)["config"], config)


def load_effective_state(project: str | Path) -> dict[str, Any]:
    return load_json(effective_paths(project)["state"], DEFAULT_STATE)


def save_effective_state(project: str | Path, state: dict[str, Any]) -> None:
    save_json(effective_paths(project)["state"], state)


def append_event(project: str | Path, event_type: str, payload: dict[str, Any]) -> None:
    paths = effective_paths(project)
    path = paths["events"]
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": int(time.time()),
        "type": event_type,
        "project": str(Path(project).resolve()),
        **payload,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def load_events(project: str | Path) -> list[dict[str, Any]]:
    path = effective_paths(project)["events"]
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def metrics_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    user_prompts = [e for e in events if e.get("type") == "user_prompt"]
    pre_tool = [e for e in events if e.get("type") == "pre_tool"]
    stop = [e for e in events if e.get("type") == "stop"]
    outcomes = [e for e in events if e.get("type") == "outcome"]
    strict_activations = sum(1 for e in user_prompts if e.get("runtime_mode") == "lateral_strict")
    lateral_activations = sum(1 for e in user_prompts if str(e.get("runtime_mode", "")).startswith("lateral_"))
    pre_tool_denies = sum(1 for e in pre_tool if e.get("decision") == "deny")
    stop_blocks = sum(1 for e in stop if e.get("decision") == "block")
    resolved_outcomes = sum(1 for e in outcomes if e.get("resolved") is True)
    ratings = [float(e["rating"]) for e in outcomes if isinstance(e.get("rating"), (int, float))]
    return {
        "events": len(events),
        "user_prompts": len(user_prompts),
        "lateral_activations": lateral_activations,
        "strict_activations": strict_activations,
        "activation_rate": lateral_activations / max(1, len(user_prompts)),
        "strict_activation_rate": strict_activations / max(1, len(user_prompts)),
        "pre_tool_calls": len(pre_tool),
        "pre_tool_denies": pre_tool_denies,
        "deny_rate": pre_tool_denies / max(1, len(pre_tool)),
        "stop_calls": len(stop),
        "stop_blocks": stop_blocks,
        "stop_block_rate": stop_blocks / max(1, len(stop)),
        "outcomes": len(outcomes),
        "resolved_outcomes": resolved_outcomes,
        "resolve_rate": resolved_outcomes / max(1, len(outcomes)),
        "average_rating": sum(ratings) / max(1, len(ratings)),
    }


def compute_metrics(project: str | Path) -> dict[str, Any]:
    return metrics_from_events(load_events(project))


def compute_workspace_metrics(project: str | Path) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in load_events(project):
        workspace = str(event.get("project") or "<unknown>")
        grouped.setdefault(workspace, []).append(event)
    return {workspace: metrics_from_events(events) for workspace, events in sorted(grouped.items())}


def normalize_text(text: str) -> str:
    lowered = text.lower()
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", lowered)
        if not unicodedata.combining(ch)
    )


def classify(prompt: str, failed_attempts: int = 0) -> Classification:
    text = normalize_text(prompt)
    score = 0
    reasons: list[str] = []
    negative_reasons: list[str] = []

    for signal, weight in POSITIVE_SIGNALS.items():
        if signal in text:
            score += weight
            reasons.append(signal.replace(" ", "_"))

    for signal, weight in NEGATIVE_SIGNALS.items():
        if signal in text:
            score += weight
            negative_reasons.append(signal.replace(" ", "_"))

    if failed_attempts >= 2:
        score += 2
        reasons.append("two_prior_failed_attempts")

    if score >= 4:
        mode = "lateral_strict"
    elif score >= 2:
        mode = "lateral_lite"
    else:
        mode = "direct"

    if mode == "lateral_strict" and design_planning_context(text, reasons) and not strict_failure_context(text, reasons):
        mode = "lateral_lite"

    return Classification(mode=mode, score=score, reasons=reasons, negative_reasons=negative_reasons)


def design_planning_context(text: str, reasons: list[str]) -> bool:
    design_words = {"plan", "choose", "design", "disenar", "diseñar", "arquitectura", "architecture"}
    design_reasons = {
        "arquitectura",
        "architecture",
        "api_design",
        "tradeoff",
        "refactor",
        "risky_refactor",
        "boundaries",
        "rollback",
        "observability",
    }
    return any(word in text for word in design_words) or bool(set(reasons) & design_reasons)


def strict_failure_context(text: str, reasons: list[str]) -> bool:
    strict_reasons = {
        "root_cause",
        "causa_raiz",
        "intermitente",
        "flaky",
        "a_veces",
        "sometimes",
        "sin_repro",
        "no_repro",
        "no_logro_reproducir",
        "cannot_reproduce",
        "desaparece",
        "disappear",
        "missing_later",
        "duplicados",
        "duplicated",
        "regression",
        "after_deploy",
        "staging_fails",
        "only_staging",
        "ci_fails",
        "local_passes",
        "race",
        "carrera",
        "cross-layer",
        "cross_layer",
        "multi-layer",
        "varias_capas",
        "ui,_api",
        "webhook",
        "never_arrives",
        "marked_paid",
        "stale",
        "old_schema",
        "schema",
        "after_redirect",
        "totals",
        "differ",
        "subset",
        "disagree",
        "mismatch",
        "distinto",
        "incident",
        "incidente",
    }
    failure_words = {"fails", "failure", "bug", "error", "broken", "rompe", "falla", "fallo"}
    return bool(set(reasons) & strict_reasons) or any(word in text for word in failure_words)


def resolve_runtime_mode(config: dict[str, Any], classification: Classification) -> str:
    configured = config.get("mode", "off")
    if not config.get("enabled") or configured == "off":
        return "off"
    if classification.mode == "direct":
        return "direct"
    if configured == "lite":
        return "lateral_lite"
    if configured == "strict":
        return "lateral_strict"
    return classification.mode


def distinct_hypotheses(hypotheses: list[dict[str, Any]]) -> int:
    seen = set()
    for hypothesis in hypotheses:
        key = (
            hypothesis.get("mechanism_class"),
            hypothesis.get("layer"),
            hypothesis.get("first_probe") or hypothesis.get("probe"),
            hypothesis.get("falsify_signal"),
        )
        seen.add(key)
    return len(seen)


def can_write(state: dict[str, Any]) -> tuple[bool, str]:
    if state.get("runtime_mode") != "lateral_strict":
        return True, "not in lateral strict mode"

    if not state.get("anchor"):
        return False, "missing anchor"

    hypotheses = state.get("hypotheses", [])
    if distinct_hypotheses(hypotheses) < 2:
        return False, "need at least two materially distinct hypotheses"

    for hypothesis in hypotheses:
        if not (hypothesis.get("first_probe") or hypothesis.get("probe")):
            return False, f"hypothesis {hypothesis.get('id', '<unknown>')} has no probe"

    if state.get("phase") not in {"converged", "implemented", "validated"} and not state.get("winner"):
        return False, "no converged winning hypothesis yet"

    return True, "strict gate satisfied"


def can_stop(state: dict[str, Any]) -> tuple[bool, str]:
    if state.get("runtime_mode") in {"off", "direct"}:
        return True, "no lateral closure needed"

    validation = state.get("validation", {})
    if validation.get("result") in {"passed", "not_applicable"}:
        return True, "validated"
    if validation.get("result") == "not_run" and validation.get("reason_if_not_run"):
        return True, "validation exception explained"
    return False, "missing validation or explicit validation exception"


def is_write_tool(tool_name: str | None) -> bool:
    if not tool_name:
        return False
    return tool_name in WRITE_TOOLS or tool_name.lower() in {tool.lower() for tool in WRITE_TOOLS}


def is_risky_bash(command: str) -> bool:
    return any(pattern.search(command) for pattern in RISKY_BASH_PATTERNS)


def apply_checkpoint(state: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
    updated = dict(state)
    for key in ("anchor", "hypotheses", "probes", "evidence", "ranking", "winner", "validation", "risks"):
        if key in checkpoint:
            updated[key] = checkpoint[key]

    if updated.get("winner"):
        updated["phase"] = "converged"
    elif updated.get("hypotheses"):
        updated["phase"] = "hypotheses_ready"
    elif updated.get("anchor"):
        updated["phase"] = "anchored"
    return updated


def build_lateral_context(runtime_mode: str, classification: Classification) -> str:
    if runtime_mode == "lateral_strict":
        enforcement = "Strict gate active: do not edit until anchor, hypotheses, probes, and convergence are recorded."
    else:
        enforcement = "Lite mode active: use lateral workflow, but edits are not blocked."
    reasons = ", ".join(classification.reasons) or "none"
    return (
        f"Lateral mode: {runtime_mode}\n"
        f"Activation score: {classification.score}\n"
        f"Reasons: {reasons}\n"
        f"{enforcement}\n"
        "Before editing, anchor the task, generate materially distinct hypotheses, "
        "choose cheap discriminating probes, gather read-only evidence, then converge."
    )


def update_state_from_prompt(project: str | Path, prompt: str) -> tuple[dict[str, Any], Classification]:
    config = load_effective_config(project)
    state = load_effective_state(project)
    classification = classify(prompt, failed_attempts=int(state.get("failed_attempts", 0)))
    runtime_mode = resolve_runtime_mode(config, classification)
    state.update(
        {
            "runtime_mode": runtime_mode,
            "configured_mode": config.get("mode", "off"),
            "phase": "classified" if runtime_mode not in {"off", "direct"} else "idle",
            "activation": asdict(classification),
        }
    )
    if runtime_mode in {"off", "direct"}:
        state.update({"anchor": None, "hypotheses": [], "probes": [], "ranking": [], "winner": None})
    save_effective_state(project, state)
    return state, classification


DEFAULT_EVAL_FIXTURES = [
    {"id": "simple-typo", "kind": "simple", "prompt": "Fix the typo in README", "expected": "direct"},
    {"id": "simple-lint", "kind": "simple", "prompt": "Fix the lint error in src/foo.ts", "expected": "direct"},
    {"id": "simple-rename", "kind": "simple", "prompt": "Renombrar variable local en un solo archivo", "expected": "direct"},
    {"id": "simple-format", "kind": "simple", "prompt": "Aplicar formato prettier al archivo", "expected": "direct"},
    {
        "id": "ambiguous-debug",
        "kind": "ambiguous",
        "prompt": "Hay un bug intermitente y cross-layer en el save del modal",
        "expected": "lateral_strict",
    },
    {
        "id": "flaky-root-cause",
        "kind": "ambiguous",
        "prompt": "Flaky test sin repro estable, busca root cause antes de tocar codigo",
        "expected": "lateral_strict",
    },
    {
        "id": "incident",
        "kind": "ambiguous",
        "prompt": "Incidente de latencia con causa raiz incierta y varias capas posibles",
        "expected": "lateral_strict",
    },
    {
        "id": "architecture",
        "kind": "ambiguous",
        "prompt": "Disenar arquitectura de batch processing con rollback y sin romper SLA",
        "expected": "lateral_lite",
    },
    {
        "id": "explicit-lateral",
        "kind": "ambiguous",
        "prompt": "Usa modo lateral y genera hipotesis antes de editar",
        "expected": "lateral_strict",
    },
]


def load_eval_fixtures(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("eval fixture file must contain a JSON list")

    fixtures: list[dict[str, Any]] = []
    for index, raw in enumerate(payload):
        if not isinstance(raw, dict):
            raise ValueError(f"fixture at index {index} must be an object")
        missing = {"id", "kind", "prompt", "expected"} - set(raw)
        if missing:
            raise ValueError(f"fixture {raw.get('id', index)} missing fields: {', '.join(sorted(missing))}")
        if raw["kind"] not in {"simple", "ambiguous"}:
            raise ValueError(f"fixture {raw['id']} has invalid kind: {raw['kind']}")
        if raw["expected"] not in {"direct", "lateral_lite", "lateral_strict"}:
            raise ValueError(f"fixture {raw['id']} has invalid expected mode: {raw['expected']}")
        fixtures.append(
            {
                "id": str(raw["id"]),
                "kind": str(raw["kind"]),
                "prompt": str(raw["prompt"]),
                "expected": str(raw["expected"]),
            }
        )
    return fixtures


def run_classifier_eval(config_mode: str = "auto", fixtures: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    config.update({"enabled": True, "mode": config_mode})
    eval_fixtures = fixtures if fixtures is not None else DEFAULT_EVAL_FIXTURES
    rows = []
    passed = 0
    false_activations = 0
    missed_activations = 0
    for fixture in eval_fixtures:
        classification = classify(fixture["prompt"])
        runtime = resolve_runtime_mode(config, classification)
        expected = fixture["expected"]
        ok = runtime == expected
        passed += int(ok)
        if fixture["kind"] == "simple" and runtime != "direct":
            false_activations += 1
        if fixture["kind"] == "ambiguous" and runtime == "direct":
            missed_activations += 1
        rows.append(
            {
                "id": fixture["id"],
                "kind": fixture["kind"],
                "expected": expected,
                "actual": runtime,
                "score": classification.score,
                "passed": ok,
            }
        )

    simple_state = dict(DEFAULT_STATE)
    simple_state["runtime_mode"] = "direct"

    ambiguous_state = dict(DEFAULT_STATE)
    ambiguous_state["runtime_mode"] = "lateral_strict"
    ambiguous_state["phase"] = "classified"

    checkpointed_state = apply_checkpoint(
        ambiguous_state,
        {
            "anchor": {"problem": "save sometimes fails"},
            "hypotheses": [
                {
                    "id": "H1",
                    "mechanism_class": "ordering_race",
                    "layer": "frontend",
                    "first_probe": "inspect submit and close ordering",
                },
                {
                    "id": "H2",
                    "mechanism_class": "contract_mismatch",
                    "layer": "api",
                    "first_probe": "compare payload and schema",
                },
            ],
            "winner": "H1",
        },
    )
    simple_allowed, _ = can_write(simple_state)
    ambiguous_allowed, _ = can_write(ambiguous_state)
    checkpoint_allowed, _ = can_write(checkpointed_state)
    gate_checks = {
        "simple_write_allowed": simple_allowed,
        "ambiguous_write_blocked_before_checkpoint": not ambiguous_allowed,
        "ambiguous_write_allowed_after_checkpoint": checkpoint_allowed,
    }
    gate_passed = all(gate_checks.values())

    return {
        "passed": passed + int(gate_passed),
        "total": len(rows) + 1,
        "classifier_passed": passed,
        "classifier_total": len(rows),
        "false_activation_rate": false_activations / max(1, sum(1 for row in rows if row["kind"] == "simple")),
        "missed_activation_rate": missed_activations / max(1, sum(1 for row in rows if row["kind"] == "ambiguous")),
        "gate_checks": gate_checks,
        "rows": rows,
    }


def run_eval_suite(paths: list[str | Path], config_mode: str = "auto") -> dict[str, Any]:
    file_results: list[dict[str, Any]] = []
    classifier_passed = 0
    classifier_total = 0
    suite_passed = 0
    suite_total = 0
    simple_total = 0
    ambiguous_total = 0
    false_activation_count = 0
    missed_activation_count = 0

    for path in paths:
        fixtures = load_eval_fixtures(path)
        result = run_classifier_eval(config_mode, fixtures)
        file_results.append(
            {
                "path": str(path),
                "passed": result["passed"],
                "total": result["total"],
                "classifier_passed": result["classifier_passed"],
                "classifier_total": result["classifier_total"],
                "false_activation_rate": result["false_activation_rate"],
                "missed_activation_rate": result["missed_activation_rate"],
            }
        )
        classifier_passed += int(result["classifier_passed"])
        classifier_total += int(result["classifier_total"])
        suite_passed += int(result["passed"])
        suite_total += int(result["total"])

        rows = result["rows"]
        simple_rows = [row for row in rows if row["kind"] == "simple"]
        ambiguous_rows = [row for row in rows if row["kind"] == "ambiguous"]
        simple_total += len(simple_rows)
        ambiguous_total += len(ambiguous_rows)
        false_activation_count += sum(1 for row in simple_rows if row["actual"] != "direct")
        missed_activation_count += sum(1 for row in ambiguous_rows if row["actual"] == "direct")

    return {
        "fixture_files": len(paths),
        "suite_passed": suite_passed,
        "suite_total": suite_total,
        "classifier_passed": classifier_passed,
        "classifier_total": classifier_total,
        "false_activation_rate": false_activation_count / max(1, simple_total),
        "missed_activation_rate": missed_activation_count / max(1, ambiguous_total),
        "files": file_results,
    }
