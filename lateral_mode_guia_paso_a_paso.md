---
title: "Guia paso a paso para implementar el modo lateral"
subtitle: "Claude Code primero, Codex como adapter guiado, orquestador externo como V2/V3"
author: "OpenAI - GPT-5.4 Pro"
date: "19 abril 2026"
lang: es
toc: true
toc-depth: 3
---

# Guia paso a paso para implementar el modo lateral

Esta guia baja la investigacion V4 a una implementacion concreta. La ruta recomendada es:

1. construir primero una version standalone en Claude Code;
2. medir si mejora tareas ambiguas;
3. recien despues empaquetar como plugin;
4. agregar adapter Codex con honestidad sobre sus limites;
5. si se necesita paridad real, construir un orquestador externo.

## 0. Principio de implementacion

No construyas “creatividad”. Construí una maquina de estados:

```text
classified -> anchored -> hypotheses_ready -> probes_ready -> evidence_ready -> converged -> implemented -> validated
```

Y una regla:

```text
En lateral_strict, no se permite Edit/Write si no existe:
anchor + >=2 hipotesis distintas + >=1 probe por hipotesis + convergencia o razon explicita.
```

## 1. Estructura inicial del repo

Crear:

```bash
mkdir -p lateral-mode/{core,claude/.claude/{skills,agents,hooks,state},codex/.codex/{agents,hooks},codex/.agents/skills,eval/{fixtures,rubrics,results}}
cd lateral-mode
```

Estructura objetivo:

```text
lateral-mode/
  core/
    state_store.py
    classifier.py
    scorer.py
    policy.py
    telemetry.py
  claude/
    .claude/
      CLAUDE.md
      settings.json
      state/
      skills/
        lateral-debug/SKILL.md
        lateral-design/SKILL.md
      agents/
        reframer.md
        skeptic.md
        verifier.md
      hooks/
        classify_prompt.py
        block_pre_tool.py
        record_post_tool.py
        validate_stop.py
  codex/
    AGENTS.md
    .agents/
      skills/
        lateral-debug/SKILL.md
        lateral-design/SKILL.md
    .codex/
      config.toml
      hooks.json
      agents/
        reframer.toml
        verifier.toml
        implementer.toml
      hooks/
        user_prompt_submit.py
        bash_guard.py
        stop_continue.py
  eval/
    fixtures/
    rubrics/
    run_eval.py
```

## 2. Core comun

### 2.1 `core/state_store.py`

Objetivo: leer y escribir estado JSON de forma atomica. Cada hook corre como proceso separado, asi que no dependas de memoria en proceso.

```python
# core/state_store.py
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

DEFAULT_STATE = {
    "schema_version": "4.0",
    "mode": "direct",
    "phase": "classified",
    "activation": {"score": 0, "reasons": [], "negative_reasons": []},
    "anchor": None,
    "hypotheses": [],
    "probes": [],
    "evidence": [],
    "ranking": [],
    "winner": None,
    "implementation": {"files_changed": [], "diff_summary": ""},
    "validation": {"commands": [], "result": "pending", "reason_if_not_run": ""},
    "risks": [],
    "updated_at": None,
}


def load_state(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return dict(DEFAULT_STATE)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # Fail closed for policy state: corrupted state should not permit writes in strict mode.
        s = dict(DEFAULT_STATE)
        s["mode"] = "lateral_strict"
        s["phase"] = "blocked"
        s["risks"] = ["state_file_corrupt"]
        return s


def save_state(path: str | Path, state: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = int(time.time())
    fd, tmp = tempfile.mkstemp(prefix=p.name, dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
```

### 2.2 `core/classifier.py`

```python
# core/classifier.py
from __future__ import annotations

from dataclasses import dataclass

POSITIVE = {
    "root cause": 2,
    "non-obvious": 2,
    "intermittent": 1,
    "flaky": 1,
    "race": 1,
    "architecture": 1,
    "incident": 2,
    "cross-layer": 2,
    "what else could explain": 2,
    "repeated failed": 2,
}

NEGATIVE = {
    "typo": -2,
    "format": -2,
    "lint": -2,
    "single file": -1,
    "mechanical": -2,
    "just rename": -2,
}

@dataclass
class Classification:
    mode: str
    score: int
    reasons: list[str]
    negative_reasons: list[str]


def classify(prompt: str, failed_attempts: int = 0) -> Classification:
    text = prompt.lower()
    score = 0
    reasons: list[str] = []
    negs: list[str] = []

    if "lateral" in text or "hipotesis" in text or "hypoth" in text:
        score += 3
        reasons.append("explicit_lateral_request")

    for k, v in POSITIVE.items():
        if k in text:
            score += v
            reasons.append(k.replace(" ", "_"))

    for k, v in NEGATIVE.items():
        if k in text:
            score += v
            negs.append(k.replace(" ", "_"))

    if failed_attempts >= 2:
        score += 2
        reasons.append("two_prior_failed_attempts")

    if score >= 4:
        mode = "lateral_strict"
    elif score >= 2:
        mode = "lateral_lite"
    else:
        mode = "direct"

    return Classification(mode=mode, score=score, reasons=reasons, negative_reasons=negs)
```

### 2.3 `core/scorer.py`

```python
# core/scorer.py
from __future__ import annotations

WEIGHTS = {
    "evidence_fit": 0.30,
    "discriminative_power": 0.25,
    "feasibility": 0.15,
    "useful_novelty": 0.10,
    "reversibility": 0.10,
    "blast_radius_control": 0.05,
    "validation_path_clarity": 0.05,
    "speculation_penalty": -0.20,
    "duplicate_penalty": -0.15,
    "security_risk_penalty": -0.10,
}


def score_hypothesis(h: dict) -> float:
    total = 0.0
    for k, w in WEIGHTS.items():
        total += w * float(h.get(k, 0.0))
    return round(total, 4)


def strong_winner(ranking: list[dict]) -> bool:
    if not ranking:
        return False
    if len(ranking) == 1:
        return ranking[0].get("total", 0) >= 0.72
    best, second = ranking[0], ranking[1]
    return (
        best.get("total", 0) >= 0.72
        and best.get("total", 0) - second.get("total", 0) >= 0.12
        and best.get("validation_path_clarity", 0) >= 0.5
    )
```

### 2.4 `core/policy.py`

```python
# core/policy.py
from __future__ import annotations

WRITE_TOOLS = {"Edit", "Write", "MultiEdit"}
RISKY_TOOLS = {"Bash", "WebSearch", "WebFetch"}


def distinct_hypotheses(hypotheses: list[dict]) -> int:
    seen = set()
    for h in hypotheses:
        key = (
            h.get("mechanism_class"),
            h.get("layer"),
            h.get("first_probe") or h.get("probe"),
        )
        seen.add(key)
    return len(seen)


def can_write(state: dict) -> tuple[bool, str]:
    if state.get("mode") not in {"lateral_strict"}:
        return True, "not in strict mode"

    if not state.get("anchor"):
        return False, "missing anchor"

    if distinct_hypotheses(state.get("hypotheses", [])) < 2:
        return False, "need at least two materially distinct hypotheses"

    for h in state.get("hypotheses", []):
        if not (h.get("first_probe") or h.get("probe")):
            return False, f"hypothesis {h.get('id')} has no probe"

    if state.get("phase") not in {"converged", "implemented", "validated"} and not state.get("winner"):
        return False, "no converged winning hypothesis yet"

    return True, "strict-mode write gate satisfied"


def can_stop(state: dict) -> tuple[bool, str]:
    if state.get("mode") == "direct":
        return True, "direct mode"

    validation = state.get("validation", {})
    if validation.get("result") in {"passed", "not_applicable"}:
        return True, "validated"
    if validation.get("result") == "not_run" and validation.get("reason_if_not_run"):
        return True, "validation explicitly explained"
    return False, "missing validation or explicit validation exception"
```

## 3. Implementacion Claude Code standalone

Entrar a `lateral-mode/claude`.

### 3.1 `CLAUDE.md`

Crear `claude/.claude/CLAUDE.md`:

```md
# Lateral mode policy

Use direct mode for localized, obvious, mechanical changes.

Use lateral mode for ambiguous debugging, intermittent failures, cross-layer bugs,
architecture decisions, incident response, root-cause analysis, API design, naming,
or after two failed attempts.

When lateral mode is active:
1. Do not edit before producing an anchor.
2. Produce 3-5 materially distinct hypotheses.
3. Each hypothesis must differ by mechanism, layer, first probe, or falsifier.
4. Each hypothesis must include one cheap discriminating probe.
5. Prefer read-only evidence before implementation.
6. Converge before editing.
7. Make the smallest reversible change.
8. End with validation: tests, lint, typecheck, reproduction, or an explicit reason.
```

### 3.2 Skill `lateral-debug`

Crear `claude/.claude/skills/lateral-debug/SKILL.md`:

```md
---
name: lateral-debug
description: Use for ambiguous, intermittent, cross-layer, flaky, or repeatedly failing bugs. Do not use for obvious localized fixes.
context: fork
agent: Explore
allowed-tools: Read, Glob, Grep, Bash
---

Research the debugging task in lateral mode.

Return JSON-like Markdown with:

1. anchor:
   - problem
   - symptoms
   - known facts
   - unknowns
   - success criteria

2. hypotheses: 3 to 5 materially distinct hypotheses.
   Each must include:
   - id
   - frame
   - mechanism_class
   - layer
   - first_probe
   - confirm_signal
   - falsify_signal
   - estimated_cost
   - estimated_risk

3. probes:
   - cheapest discriminating probe per hypothesis
   - expected observation

4. ranking:
   - top 2 hypotheses
   - why each survives

Do not edit files. Do not propose a patch yet unless the evidence already makes one path dominant.
```

### 3.3 Skill `lateral-design`

Crear `claude/.claude/skills/lateral-design/SKILL.md`:

```md
---
name: lateral-design
description: Use for architecture, API design, naming, refactor strategy, rollout planning, or feature design with real tradeoffs.
context: fork
agent: Plan
allowed-tools: Read, Glob, Grep
---

Explore design alternatives before implementation.

Return:
1. Anchor and constraints.
2. 3-5 design frames.
3. Tradeoff table: correctness, complexity, rollout, reversibility, observability, security.
4. Recommended path.
5. Validation plan.

Do not edit files.
```

### 3.4 Agente `reframer`

Crear `claude/.claude/agents/reframer.md`:

```md
---
name: reframer
description: Generates materially distinct frames and probes for ambiguous debugging or design tasks.
model: sonnet
effort: medium
maxTurns: 10
disallowedTools: Write, Edit
---

You are a read-only reframing agent.
Generate different causal or design frames.
Do not edit files.
Every frame must imply a different first probe or falsifier.
Penalize cosmetic differences.
```

### 3.5 Agente `skeptic`

Crear `claude/.claude/agents/skeptic.md`:

```md
---
name: skeptic
description: Reviews hypotheses for duplication, speculation, drift, and missing validation.
model: sonnet
effort: medium
maxTurns: 8
disallowedTools: Write, Edit
---

You are a skeptical reviewer.
Reject hypotheses that are duplicated, untestable, too speculative, or disconnected from the anchor.
Prefer evidence over elegance.
```

### 3.6 Agente `verifier`

Crear `claude/.claude/agents/verifier.md`:

```md
---
name: verifier
description: Designs cheap probes and validation commands for the winning hypothesis.
model: sonnet
effort: medium
maxTurns: 8
disallowedTools: Write, Edit
---

You design probes and validation plans.
For every hypothesis, identify the cheapest action that can confirm or falsify it.
Prefer tests, logs, grep, targeted file reads, and reproducible commands.
```

### 3.7 `settings.json` con hooks

Crear `claude/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/classify_prompt.py"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|Bash|WebSearch|WebFetch",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/block_pre_tool.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Read|Grep|Glob|Bash|Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/record_post_tool.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/validate_stop.py"
          }
        ]
      }
    ]
  }
}
```

Nota: para scripts de produccion, usar paths absolutos o `$CLAUDE_PROJECT_DIR` si tu version lo expone en tu entorno. Evita depender de cwd si vas a compartirlo.

### 3.8 Hook `classify_prompt.py`

Crear `claude/.claude/hooks/classify_prompt.py`:

```python
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT.parent / "core"))

from classifier import classify
from state_store import load_state, save_state

STATE = ROOT / ".claude" / "state" / "lateral_state.json"

payload = json.load(sys.stdin)
prompt = payload.get("prompt", "")
state = load_state(STATE)
failed_attempts = int(state.get("failed_attempts", 0))
cls = classify(prompt, failed_attempts=failed_attempts)

state["mode"] = cls.mode
state["phase"] = "classified"
state["activation"] = {
    "score": cls.score,
    "reasons": cls.reasons,
    "negative_reasons": cls.negative_reasons,
}
save_state(STATE, state)

if cls.mode == "direct":
    sys.exit(0)

context = f"""
Lateral mode active: {cls.mode}
Activation score: {cls.score}
Reasons: {', '.join(cls.reasons) or 'none'}

Before editing, create an anchor, at least two materially distinct hypotheses,
and one cheap discriminating probe per hypothesis. Prefer read-only evidence.
""".strip()

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": context
    }
}))
```

### 3.9 Hook `block_pre_tool.py`

Crear `claude/.claude/hooks/block_pre_tool.py`:

```python
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT.parent / "core"))

from state_store import load_state
from policy import can_write

STATE = ROOT / ".claude" / "state" / "lateral_state.json"
WRITE_TOOLS = {"Edit", "Write", "MultiEdit"}

payload = json.load(sys.stdin)
tool = payload.get("tool_name")
state = load_state(STATE)

if state.get("mode") != "lateral_strict":
    sys.exit(0)

if tool in WRITE_TOOLS:
    ok, reason = can_write(state)
    if not ok:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Lateral strict gate: {reason}. Run lateral-debug/design first and update state."
            }
        }))
        sys.exit(0)

# Optional: ask before risky web/MCP-like operations in strict mode.
if tool in {"WebSearch", "WebFetch"}:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "External content is untrusted. Confirm this evidence source is needed."
        }
    }))
    sys.exit(0)

sys.exit(0)
```

### 3.10 Hook `record_post_tool.py`

Crear `claude/.claude/hooks/record_post_tool.py`:

```python
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT.parent / "core"))

from state_store import load_state, save_state

STATE = ROOT / ".claude" / "state" / "lateral_state.json"

payload = json.load(sys.stdin)
state = load_state(STATE)

if state.get("mode") == "direct":
    sys.exit(0)

event = {
    "tool": payload.get("tool_name"),
    "input_summary": str(payload.get("tool_input", {}))[:500],
    "record_type": "tool_observation"
}
state.setdefault("evidence", []).append(event)

# Do not over-automate phase transitions here in V1.
save_state(STATE, state)
sys.exit(0)
```

### 3.11 Hook `validate_stop.py`

Crear `claude/.claude/hooks/validate_stop.py`:

```python
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT.parent / "core"))

from state_store import load_state
from policy import can_stop

STATE = ROOT / ".claude" / "state" / "lateral_state.json"
state = load_state(STATE)

ok, reason = can_stop(state)
if ok:
    sys.exit(0)

print(json.dumps({
    "decision": "block",
    "reason": "Before stopping, finish lateral-mode closure: run validation or explicitly explain why validation was not possible. Also summarize hypotheses, winner, evidence, files changed, and residual risks."
}))
```

### 3.12 Hacer scripts ejecutables

```bash
chmod +x claude/.claude/hooks/*.py
```

### 3.13 Probar en Claude Code

Desde `lateral-mode/claude`:

```bash
claude
```

Prompt de prueba:

```text
Hay un bug intermitente y cross-layer: a veces el save del modal no persiste. Activá modo lateral y no edites hasta tener hipótesis y probes.
```

Resultado esperado:

- `classify_prompt.py` activa `lateral_strict`.
- Claude debe generar anchor/hipotesis/probes.
- Si intenta editar antes de converger, `block_pre_tool.py` lo bloquea.
- Al cerrar sin validacion, `validate_stop.py` lo fuerza a continuar.

## 4. Como actualizar estado manualmente en V1

En V1, la skill devuelve Markdown, pero el state JSON no se llena solo. Para prototipo rapido, se puede pedir a Claude:

```text
Actualiza .claude/state/lateral_state.json con el anchor, hypotheses, probes, ranking y winner según el resultado anterior. No edites código de producto.
```

Para V1.1, crear un script parser simple o una tool local para escribir estado estructurado.

## 5. Adapter Codex

Entrar a `lateral-mode/codex`.

### 5.1 `AGENTS.md`

Crear `codex/AGENTS.md`:

```md
# Lateral mode policy

Use direct mode for obvious local changes.
Use lateral mode for ambiguous debugging, intermittent bugs, architecture, API design,
incident response, root cause analysis, or after repeated failed attempts.

When lateral mode is active:
1. Produce an anchor before editing.
2. Produce 3-5 materially distinct hypotheses.
3. Each hypothesis must have a different first probe or falsifier.
4. Prefer read-only evidence.
5. Do not edit until one hypothesis is favored by evidence, or explain why the edit is itself the probe.
6. End with tests/lint/typecheck/repro or a clear reason validation was not possible.

Codex note: internal hooks may not intercept file writes. Treat this policy as guidance unless an external orchestrator is enforcing it.
```

### 5.2 Codex skills en `.agents/skills`

Crear `codex/.agents/skills/lateral-debug/SKILL.md`:

```md
---
name: lateral-debug
description: Use for ambiguous, intermittent, cross-layer, or repeatedly failing bugs. Do not use for obvious localized fixes.
---

Before editing:
1. Anchor the problem.
2. Generate 3-5 distinct hypotheses.
3. Provide one cheap discriminating probe per hypothesis.
4. Rank top 2 by evidence, discriminative power, feasibility, and reversibility.
5. Ask to spawn the reframer or verifier agent if the task is complex.
6. End with a validation plan.
```

Crear `codex/.agents/skills/lateral-design/SKILL.md`:

```md
---
name: lateral-design
description: Use for architecture, API design, naming, refactor strategy, or feature planning with tradeoffs.
---

Explore alternative designs before implementation.
Return:
- anchor
- constraints
- 3-5 design frames
- tradeoff table
- recommendation
- validation plan
```

### 5.3 Codex config

Crear `codex/.codex/config.toml`:

```toml
[features]
codex_hooks = true

[agents]
max_threads = 4
max_depth = 1
```

### 5.4 Codex custom agents

Crear `codex/.codex/agents/reframer.toml`:

```toml
name = "reframer"
description = "Read-only agent that generates materially distinct hypotheses and probes before edits."
sandbox_mode = "read-only"
model_reasoning_effort = "medium"
developer_instructions = """
Stay read-only. Generate 3-5 distinct frames.
Each frame must differ by mechanism, layer, first probe, or falsifier.
Do not edit code. Return top 2 hypotheses.
"""
```

Crear `codex/.codex/agents/verifier.toml`:

```toml
name = "verifier"
description = "Read-only agent that designs probes and validation commands."
sandbox_mode = "read-only"
model_reasoning_effort = "medium"
developer_instructions = """
Design the cheapest discriminating probe for each hypothesis.
Prefer tests, grep, logs, schema inspection, and targeted repros.
Do not edit code.
"""
```

Crear `codex/.codex/agents/implementer.toml`:

```toml
name = "implementer"
description = "Implementation agent for minimal reversible changes after convergence."
model_reasoning_effort = "medium"
developer_instructions = """
Implement only after the parent has selected a winning hypothesis.
Make the smallest reversible change. Run validation.
"""
```

### 5.5 Codex hooks

Crear `codex/.codex/hooks.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$(git rev-parse --show-toplevel)/.codex/hooks/user_prompt_submit.py\""
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$(git rev-parse --show-toplevel)/.codex/hooks/bash_guard.py\""
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$(git rev-parse --show-toplevel)/.codex/hooks/stop_continue.py\"",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

### 5.6 Hook `user_prompt_submit.py`

Crear `codex/.codex/hooks/user_prompt_submit.py`:

```python
#!/usr/bin/env python3
import json
import sys

payload = json.load(sys.stdin)
prompt = payload.get("prompt", "").lower()
triggers = ["intermittent", "flaky", "root cause", "architecture", "incident", "cross-layer", "lateral"]

if any(t in prompt for t in triggers):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Lateral mode likely applies. Before editing, use $lateral-debug or spawn reframer/verifier agents. Codex hooks do not fully enforce file-write gates, so follow the policy explicitly."
        }
    }))
```

### 5.7 Hook `bash_guard.py`

Crear `codex/.codex/hooks/bash_guard.py`:

```python
#!/usr/bin/env python3
import json
import re
import sys

payload = json.load(sys.stdin)
cmd = payload.get("tool_input", {}).get("command", "")

blocked = [
    r"rm\s+-rf\s+/",
    r"git\s+push\s+.*--force",
    r"curl\s+.*\|\s*sh",
    r"wget\s+.*\|\s*sh",
]

if any(re.search(p, cmd) for p in blocked):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Blocked risky Bash command."
        }
    }))
```

### 5.8 Hook `stop_continue.py`

Crear `codex/.codex/hooks/stop_continue.py`:

```python
#!/usr/bin/env python3
import json
import sys

payload = json.load(sys.stdin)
msg = (payload.get("last_assistant_message") or "").lower()

needs_validation = any(k in msg for k in ["changed", "implemented", "fixed", "modified"])
has_validation = any(k in msg for k in ["test", "lint", "typecheck", "validated", "validation", "repro"])

if needs_validation and not has_validation:
    print(json.dumps({
        "decision": "block",
        "reason": "Before stopping, report validation: tests, lint, typecheck, repro, or explain why validation was not possible."
    }))
```

### 5.9 Probar Codex

Desde `lateral-mode/codex`:

```bash
codex
```

Prompt recomendado:

```text
Usa $lateral-debug. Hay un bug intermitente en el save del modal. Spawn reframer y verifier en read-only, espera sus resultados, y no implementes hasta elegir una hipótesis ganadora.
```

## 6. Empaquetar Claude como plugin cuando funcione

Solo despues de validar standalone.

Estructura:

```text
my-lateral-plugin/
  .claude-plugin/
    plugin.json
  skills/
    lateral-debug/SKILL.md
    lateral-design/SKILL.md
  agents/
    reframer.md
    skeptic.md
    verifier.md
  hooks/
    hooks.json
  scripts/
    classify_prompt.py
    block_pre_tool.py
    record_post_tool.py
    validate_stop.py
```

`plugin.json` minimo:

```json
{
  "name": "lateral-mode",
  "version": "0.1.0",
  "description": "Divergent-convergent workflow for ambiguous coding tasks",
  "author": "your-team"
}
```

Ajustar scripts para usar rutas de plugin y estado persistente. En plugin, preferir `${CLAUDE_PLUGIN_DATA}` para estado durable.

## 7. Evaluacion inicial

Crear `eval/fixtures/tasks.yaml`:

```yaml
- id: simple-lint-001
  type: simple
  prompt: "Fix the lint error in src/foo.ts"
  expected_mode: direct

- id: debug-flaky-001
  type: ambiguous_debug
  prompt: "The settings modal save sometimes fails after closing. Find root cause."
  expected_mode: lateral_strict

- id: architecture-001
  type: architecture
  prompt: "Design batch processing with rollback and no SLA regression."
  expected_mode: lateral_lite
```

Crear metricas manuales al principio:

```text
- activated correctly? yes/no
- distinct hypotheses count
- probes count
- did it edit before convergence? yes/no
- validation present? yes/no
- user/developer preference
```

## 8. Criterios para decir que el MVP sirve

Debe cumplir:

1. activa en la mayoria de bugs ambiguos;
2. no activa en tareas simples;
3. bloquea ediciones prematuras en Claude;
4. aumenta claridad de root cause;
5. no duplica costo en tareas simples;
6. mejora confianza del developer;
7. no introduce riesgos de seguridad nuevos sin mitigacion.

## 9. Roadmap practico

### Dia 1

- Crear scaffold.
- Implementar core state/classifier/policy.
- Crear Claude skills.

### Dia 2

- Crear Claude hooks.
- Probar gate de Edit/Write.
- Ajustar mensajes.

### Dia 3

- Agregar scorer y formato de estado.
- Crear 10 fixtures.

### Dia 4

- Adapter Codex.
- Corregir skills en `.agents/skills`.
- Crear custom agents.

### Dia 5

- Evaluacion manual A/B.
- Ajustar activacion.
- Documentar failure modes.

### Semana 2-4

- PostTool evidence recorder serio.
- Telemetria JSONL/OTel.
- Parser de outputs a state.
- Primer plugin Claude.
- Dashboard minimo.

### Trimestre

- Orquestador externo.
- MCP read-only a CI/issues/docs.
- Approval service.
- Eval interno 100+ tasks.

## 10. Prompts de uso

### Debug dificil

```text
Activa modo lateral. Antes de editar, genera anchor, 3-5 hipótesis distintas y probes baratos. Usa evidencia del repo/tests y converge a una hipótesis ganadora antes del patch.
```

### Arquitectura

```text
Usa lateral-design. Dame 4 diseños alternativos, tradeoffs, riesgos, plan de migración, validación y recomendación final. No implementes todavía.
```

### Codex con subagents

```text
Usa $lateral-debug. Spawn reframer para hipótesis y verifier para probes. Esperá ambos resultados. Después elegí top-1/top-2 y recién ahí pedime permiso para implementar.
```

## 11. Checklist final

Antes de editar en lateral strict:

- [ ] anchor existe
- [ ] hay 2+ hipotesis distintas
- [ ] cada hipotesis tiene probe
- [ ] hay evidencia read-only
- [ ] hay ranking
- [ ] hay winner o razon para experimento reversible

Antes de cerrar:

- [ ] tests/lint/typecheck/repro corridos, o razon clara
- [ ] hipotesis ganadora explicada
- [ ] cambios resumidos
- [ ] riesgos residuales listados
- [ ] si fallo validacion, se registro reframe

## 12. Referencias usadas

- Claude Code Plugins: https://code.claude.com/docs/en/plugins
- Claude Code Plugins Reference: https://code.claude.com/docs/en/plugins-reference
- Claude Code Skills: https://code.claude.com/docs/en/skills
- Claude Code Hooks: https://code.claude.com/docs/en/hooks
- Claude Code Subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code Monitoring: https://code.claude.com/docs/en/monitoring-usage
- Codex AGENTS.md: https://developers.openai.com/codex/guides/agents-md
- Codex Skills: https://developers.openai.com/codex/skills
- Codex Hooks: https://developers.openai.com/codex/hooks
- Codex Subagents: https://developers.openai.com/codex/subagents
- Codex MCP: https://developers.openai.com/codex/mcp
- Codex App Server: https://developers.openai.com/codex/app-server
- Codex Security: https://developers.openai.com/codex/agent-approvals-security
