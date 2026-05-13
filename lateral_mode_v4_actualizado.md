---
title: "Modo lateral para Claude Code y Codex - Version 4"
subtitle: "Investigacion actualizada, arquitectura corregida y especificacion tecnica productizable"
author: "OpenAI - GPT-5.4 Pro"
date: "19 abril 2026"
lang: es
toc: true
toc-depth: 3
---

# Modo lateral para Claude Code y Codex - Version 4

## Resumen ejecutivo

La Version 4 parte del documento `lateral_mode_v3.md` y lo endurece en tres direcciones: actualizacion de superficie real de Claude Code y Codex, mejor separacion entre guidance y enforcement, y una especificacion mas implementable del motor divergente -> evidencial -> convergente -> verificado.

La conclusion principal se mantiene, pero queda mas precisa:

> No conviene construir un “plugin creativo”. Conviene construir una **capa de politica cognitiva y verificacion** que fuerce exploracion lateral solo cuando aporta valor, y que bloquee o desaconseje ediciones antes de tener hipotesis, probes y evidencia suficiente.

La arquitectura recomendada sigue siendo **Claude Code primero**, pero V4 corrige y mejora detalles importantes:

1. En **Claude Code**, el enforcement interno es mas fuerte de lo planteado en V3 porque `PreToolUse` puede actuar sobre herramientas como `Edit`, `Write`, `Read`, `Grep`, `Glob`, `Agent`, `WebSearch`, `WebFetch`, `ExitPlanMode` y herramientas MCP, y puede devolver decisiones como `allow`, `deny`, `ask` o `defer`, ademas de modificar input en ciertos casos. Esto permite una version realmente estricta del gate lateral.
2. En **Claude Code plugins**, los agentes de plugin soportan mas campos utiles de lo que V3 habia dejado como dudoso: `tools`, `disallowedTools`, `skills`, `memory`, `background` e `isolation`, con la salvedad de que `hooks`, `mcpServers` y `permissionMode` no estan soportados para agentes empaquetados en plugin. Eso habilita un Reframer/Verifier/Skeptic mas serio.
3. En **Codex**, V4 corrige la estructura: las skills repo-scoped se guardan bajo `.agents/skills`, no bajo `.codex/skills`. La carpeta `.codex/` queda para config, hooks y agentes custom.
4. En **Codex**, `PreToolUse` y `PostToolUse` siguen siendo experimentales y hoy solo interceptan `Bash`; no interceptan `Write`, `MCP`, `WebSearch` ni otras llamadas no-shell. Por eso Codex no debe venderse como equivalente a Claude para enforcement pre-edit interno.
5. La evaluacion debe integrar telemetria real: Claude Code tiene soporte oficial de OpenTelemetry para uso, costos y actividad de tools, y Codex expone App Server/SDK para flujos con eventos, aprobaciones y trazas. En V4 esto pasa a ser parte del diseno, no un extra.
6. MCP entra recien en V2/V3 del producto, no en el MVP, porque expande mucho el area de ataque: tool poisoning, prompt injection, permisos, exfiltracion y drift.

## 0. Que cambio frente a V3

| Area | V3 | Correccion V4 | Impacto |
|---|---|---|---|
| Codex skills | Usaba `.codex/skills` en ejemplos | Debe ser `.agents/skills` para repo/user/admin/system skills | Cambia estructura del adapter Codex |
| Claude PreToolUse | Se trataba como fuerte, pero no se explotaba del todo | Soporta match contra muchas tools y MCP, no solo Bash | Gate estricto de `Edit/Write` es viable |
| Claude plugin agents | V3 era conservador con worktree/memory | Plugin agents soportan `memory`, `background`, `isolation: worktree`, `disallowedTools` | Mejor diseno de roles |
| Claude telemetry | Mencionada poco | OpenTelemetry oficial debe usarse para costos/tools/ROI | Evaluacion mas seria |
| Claude async hooks | No se distinguian suficiente | Async hooks no pueden bloquear ni decidir | Usar solo para tests/background reporting |
| Claude channels | No incluidos | Research preview para eventos externos via MCP | V3/V4 futura, no MVP |
| Codex hooks | Parciales | Confirmado: experimentales, Windows off, Pre/Post solo Bash, campos fail-open | Codex = guidance interno, enforcement externo |
| Codex custom agents | Parcial | `.codex/agents/*.toml`, built-ins `default`, `worker`, `explorer`, spawn explicito | Mejor adapter Codex |
| Research coding agents | Menos actual | Agregar Behavioral Drivers 2026, SWE-Skills-Bench 2026, Ambig-SWE, seguridad MCP/prompt injection | Justifica read-first, validate-last y skills selectivas |

## 1. Definicion del problema

### 1.1 Definicion operativa

En este proyecto, “pensamiento lateral” no significa estilo creativo, respuesta sorpresiva ni alta temperatura. Significa:

> Capacidad del sistema de **salir temporalmente del framing inicial**, generar marcos causales o de solucion materialmente distintos, obtener evidencia que discrimine entre ellos, y converger despues hacia una accion minima, reversible y validada.

La palabra importante es **sistema**. No estamos cambiando los pesos del modelo ni accediendo al razonamiento interno. Estamos imponiendo una politica externa de trabajo:

1. detectar si el problema amerita divergencia;
2. anclar el problema para evitar drift;
3. producir hipotesis distintas por mecanismo, capa o probe;
4. exigir un probe discriminante por hipotesis;
5. puntuar hipotesis por evidencia, utilidad y costo;
6. converger;
7. editar solo cuando corresponde;
8. validar.

### 1.2 Diferencias importantes

| Concepto | Que hace | Por que no alcanza |
|---|---|---|
| Chain-of-thought lineal | Una trayectoria razonada | Puede quedar atrapado en el primer framing |
| Razonamiento vertical | Optimiza dentro del marco dado | Excelente despues de elegir hipotesis, malo si el marco inicial esta mal |
| Brainstorming | Genera muchas ideas | No exige probes, evidencia ni convergencia |
| Alta temperature | Aumenta variacion superficial | No garantiza diversidad causal ni utilidad |
| Self-consistency | Varias rutas, voto por consistencia | Bueno en respuestas cerradas, insuficiente en diseno abierto |
| ToT/GoT | Search sobre rutas de pensamiento | Potente, pero caro si no se acota |
| ReAct | Razonamiento + acciones externas | Central para grounding, pero necesita politica de hipotesis |

### 1.3 Traduccion a coding agents

Para Claude Code o Codex, la traduccion mas util es:

```text
Input ambiguo o caro
  -> anchor
  -> hypotheses[3..5]
  -> probe por hipotesis
  -> read-only evidence
  -> score
  -> top-2
  -> tiebreak si hace falta
  -> patch minimo
  -> validation
  -> reporte con riesgos residuales
```

Eso es pensamiento lateral productizable.

## 2. Estado del arte actualizado

### 2.1 Benchmarks de lateral thinking e informacion incompleta

#### LatEval

LatEval evalua lateral thinking en un setting interactivo de informacion incompleta. Lo valioso para este proyecto no es el formato de puzzle, sino el hecho de medir dos cosas que un coding agent tambien necesita: calidad de preguntas/probes y capacidad de integrar informacion parcial.

**Uso en V4:** benchmark offline de politica cognitiva. No usar como runtime productivo.

#### SPLAT

SPLAT usa situation puzzles y un framework player-judge multi-turn. Aporta una idea clave para este producto: el agente no debe solo “pensar”; debe formular preguntas que reduzcan incertidumbre.

**Uso en V4:** evaluar si el motor elige probes discriminantes y evita repetir preguntas equivalentes.

#### Evaluation Hallucination en tareas multi-round

Investigaciones recientes sobre reasoning lateral multi-round advierten que la evaluacion puede introducir alucinaciones o feedback inconsistente. Para este proyecto, la leccion es que los evaluadores LLM no deben ser la unica fuente de verdad: el scoring debe apoyarse en tests, logs, repo state, diffs y criterios deterministas cuando existan.

### 2.2 Metodos multipath y search-based

#### Self-Consistency

Self-Consistency reemplaza decodificacion greedy por muestreo de multiples rutas y seleccion de la respuesta mas consistente. Sirve como idea de **votacion ligera**, pero no debe ser el mecanismo principal en tareas abiertas.

**V4:** usar solo como fallback para hipotesis cerradas o tie-break de razonamiento, no para arquitectura compleja.

#### Tree of Thoughts

Tree of Thoughts permite exploracion, evaluacion y backtracking sobre unidades de pensamiento. Es el patron mas cercano al motor V4, pero debe reducirse a **ToT-lite**: pocas ramas, poca profundidad y poda temprana.

**V4:** 3-5 ramas iniciales, maximo 1-2 rondas de probes, top-2 finalistas.

#### Graph of Thoughts

Graph of Thoughts permite recombinar rutas. Es valioso conceptualmente para arquitectura y refactors, pero demasiado caro para MVP.

**V4:** inspiracion de diseno, no runtime literal.

#### ReAct

ReAct es central porque separa este proyecto de un prompt “creativo”: razonar y actuar se intercalan. En coding agents, actuar significa leer archivos, correr tests, inspeccionar logs, consultar docs o usar MCP.

**V4:** cada hipotesis debe tener una accion de evidencia.

#### Self-Refine

Self-Refine ayuda en la fase de convergencia: revisar el plan, patch y salida final. No reemplaza la divergencia.

**V4:** aplicar despues de elegir hipotesis, no antes.

#### Reflexion

Reflexion aporta memoria verbal de fallos. Para este sistema, eso se traduce en: si dos patches fallan por la misma familia causal, registrar contradiccion y forzar reframe.

**V4:** memoria corta de sesion + optional long-term solo despues de medir.

#### Step-Back Prompting

Step-Back obliga a abstraer antes de resolver. Es muy util para la fase de anchor/reframe.

**V4:** convertirlo en regla de skill: “antes de hipotesis, formula principio o invariante de nivel superior”.

### 2.3 Debate multiagente: usar poco

El debate multiagente puede ayudar si los roles son realmente distintos. Pero la evidencia reciente muestra que el debate puede degenerar en mayoria, drift, teatralidad o repeticion. V4 usa pocos roles:

- Reframer
- Skeptic
- Verifier
- Implementer

Nada de 6-8 agentes debatiendo por defecto.

### 2.4 Evidencia especifica de coding agents

#### Ambig-SWE

Ambig-SWE estudia instrucciones subespecificadas en coding agents: detectar ambiguedad, preguntar clarificaciones y usar la interaccion para mejorar resultado. Esto respalda directamente el router V4.

#### Behavioral Drivers of Coding Agent Success and Failure

El estudio 2026 sobre trayectorias de coding agents encuentra que los agentes que recolectan contexto antes de editar y validan mas despues tienden a tener mas exito. Esto es una validacion fuerte para el principio V4:

```text
read-first -> edit-late -> validate-always
```

#### SWE-Skills-Bench

SWE-Skills-Bench muestra que las skills no son magia: muchas no mejoran nada, algunas empeoran, y el overhead puede subir mucho. Esto cambia el producto: las skills deben ser **selectivas, estrechas y evaluadas**, no un paquete enorme siempre activo.

#### Benchmarks SWE

SWE-bench Verified, SWE-bench Pro y variantes son utiles, pero no bastan. Para este producto hace falta un benchmark interno con bugs ambiguos, flakes, incidentes y tareas de arquitectura. Ademas, estudios recientes cuestionan contaminacion y realismo de algunos benchmarks publicos, asi que la evaluacion real debe incluir repos propios y tasks frescas.

### 2.5 Seguridad: MCP, skills y prompt injection

La seguridad pasa a ser parte del core V4. Estudios recientes sobre prompt injection en coding assistants y threat modeling de MCP remarcan que skills, tool metadata, repos, docs, issues y MCP servers pueden convertirse en vectores de instrucciones maliciosas.

Implicacion directa:

- fase divergente read-only;
- allowlists de MCP;
- tool schemas auditados;
- no confiar en contenido de issues/docs/web como instrucciones;
- hooks deterministas para bloquear operaciones riesgosas;
- logs/audit trail.

## 3. Superficies reales de plataforma

## 3.1 Claude Code

### 3.1.1 Lo confirmado oficialmente

Claude Code tiene una superficie fuerte para este proyecto:

- `.claude/` standalone para iteracion rapida;
- plugins empaquetados con skills, agents, hooks, MCP servers, LSP servers y monitors;
- skills con `context: fork` y `agent: Explore|Plan|general-purpose|custom`;
- hooks con lifecycle amplio;
- subagents con scopes y tool access;
- plugin agents con `tools`, `disallowedTools`, `skills`, `memory`, `background`, `isolation`;
- MCP para tools externas;
- Agent SDK para orquestacion programatica;
- OpenTelemetry para telemetria;
- channels como research preview para eventos externos.

### 3.1.2 Skills

La skill ideal para V4 es una **skill de preflight**:

- corre aislada con `context: fork`;
- usa `agent: Explore` o `Plan`;
- no edita;
- devuelve hipotesis, probes y ranking inicial.

Patron recomendado:

```yaml
---
name: lateral-debug
description: Use for ambiguous, intermittent, cross-layer, or repeatedly failing bugs. Do not use for localized obvious fixes.
context: fork
agent: Explore
allowed-tools: Read, Glob, Grep, Bash
---
```

### 3.1.3 Hooks

Hooks son el centro de enforcement:

- `UserPromptSubmit`: clasificar prompt, agregar contexto, bloquear prompts invalidos.
- `PreToolUse`: bloquear o pedir confirmacion antes de `Edit`, `Write`, `Bash`, `WebSearch`, `MCP`, etc.
- `PostToolUse`: capturar evidencia tras herramientas.
- `Stop`: impedir cierre sin validacion.
- `SubagentStart/SubagentStop`: reforzar reglas de subagentes.
- `InstructionsLoaded`: solo observabilidad; no bloqueo.

La novedad importante frente a V3: `PreToolUse` en Claude Code no es solo para Bash. V4 lo usa como gate real.

### 3.1.4 Agentes de plugin

Un plugin puede traer agentes como `reframer`, `skeptic`, `verifier` e `implementer`. Reglas:

- `reframer`, `skeptic`, `verifier`: read-only via `disallowedTools: Write, Edit`.
- `implementer`: permitido solo tras state `phase=converged`.
- `isolation: worktree` puede ser util para implementaciones paralelas o experimentales, pero no debe ser default en MVP.
- `memory` puede ayudar, pero usar con cuidado por riesgo de sesgo viejo.

### 3.1.5 MCP y channels

MCP queda para V2:

- CI/test results;
- issue tracker;
- observability;
- docs internas;
- browser/devtools.

Channels son interesantes para incident response y CI events, pero son research preview. No deben entrar en el MVP base.

### 3.1.6 Telemetria

Claude Code tiene OpenTelemetry. V4 debe emitir eventos propios compatibles:

- `lateral.activation`
- `lateral.hypothesis.generated`
- `lateral.probe.run`
- `lateral.convergence`
- `lateral.validation`
- `lateral.false_positive`
- `lateral.regret`

### 3.1.7 Limites reales

- Hooks command corren con permisos del usuario: riesgo alto.
- Async hooks no bloquean ni deciden.
- Agent Teams son experimentales y caros; no MVP.
- Full custom system prompt sirve en Agent SDK/headless, pero para producto normal conviene CLAUDE.md, skills y hooks.

## 3.2 Codex

### 3.2.1 Lo confirmado oficialmente

Codex tiene:

- `AGENTS.md` para instrucciones persistentes;
- skills bajo `.agents/skills`, `$HOME/.agents/skills`, admin y system;
- plugins que empaquetan skills, apps y MCP servers;
- custom agents/subagents bajo `.codex/agents/*.toml` o `~/.codex/agents/*.toml`;
- hooks experimentales;
- MCP con stdio y streamable HTTP;
- App Server para integracion profunda;
- SDK / uso de Codex como MCP server para orquestacion;
- sandbox y approvals.

### 3.2.2 AGENTS.md

Es la mejor capa de guidance persistente. Debe contener:

- politica de activacion lateral;
- reglas para no editar antes de hipotesis/probes;
- validacion obligatoria;
- salida final estructurada.

### 3.2.3 Skills

Correccion clave: usar `.agents/skills`, no `.codex/skills`.

Estructura:

```text
repo/
  AGENTS.md
  .agents/
    skills/
      lateral-debug/
        SKILL.md
      lateral-design/
        SKILL.md
```

### 3.2.4 Custom agents

Codex soporta custom agents en TOML:

```text
repo/
  .codex/
    agents/
      reframer.toml
      verifier.toml
      implementer.toml
```

Subagents solo se spawnean cuando se pide explicitamente. Por eso V4 Codex debe usar prompts del tipo:

```text
Usa el agente reframer para mapear hipotesis, espera su resultado, luego usa verifier para elegir probes. No edites hasta converger.
```

### 3.2.5 Hooks

Codex hooks siguen siendo utiles, pero no suficientes:

- experimentales;
- Windows deshabilitado temporalmente;
- `PreToolUse` / `PostToolUse` solo ven `Bash`;
- no interceptan `Write`, `MCP`, `WebSearch`, etc.;
- varios campos parseados no estan implementados y fallan open.

Conclusion: en Codex, el runtime interno no da enforcement equivalente a Claude. Para enforcement fuerte, usar App Server/SDK/orchestrator externo.

### 3.2.6 Seguridad

Codex tiene buena historia de sandbox/approvals:

- cloud setup con red, agent phase offline por defecto;
- local workspace-write sin network por defecto;
- read-only para planificacion;
- aprobaciones para salir del workspace, red, acciones destructivas.

Pero esto no reemplaza el gate lateral. Lo complementa.

## 4. Arquitectura V4 recomendada

## 4.1 Modos de operacion

V4 define cuatro modos, no uno solo:

| Modo | Uso | Enforce | Plataformas |
|---|---|---|---|
| Direct | tareas simples/localizadas | ninguno extra | Claude/Codex |
| Lateral Lite | ambiguedad media | guidance + skill | Claude/Codex |
| Lateral Strict | bugs/arquitectura caros | hooks + state + stop gate | Claude fuerte, Codex parcial |
| Orchestrated | enterprise/CI/incidentes | runtime externo | Claude Agent SDK / Codex App Server/SDK |

## 4.2 Arquitectura principal para Claude Code

```text
UserPromptSubmit
  -> classify_prompt.py
  -> state.phase = direct | lateral_lite | lateral_strict
  -> additionalContext si lateral

Skill/Subagent Explore
  -> anchor
  -> hypotheses
  -> probes
  -> evidence plan
  -> state.phase = evidence_ready

PreToolUse(Edit|Write|Bash|MCP|WebSearch)
  -> block_edits_until_ready.py
  -> deny/ask si falta anchor/hypotheses/probes/convergence

PostToolUse
  -> record evidence/tool result
  -> update scores

Stop
  -> validate_stop.py
  -> block continuation si falta validation o risks
```

### Componentes

- `classifier.py`: determina modo.
- `state_store.py`: JSON atomico + lock.
- `scorer.py`: scoring de hipotesis.
- `gate.py`: policy deterministica.
- `stop_validator.py`: cierre.
- `telemetry.py`: JSONL + OTel adapter.
- skills: `lateral-debug`, `lateral-design`, `lateral-incident`.
- agents: `reframer`, `skeptic`, `verifier`.

## 4.3 Arquitectura para Codex

```text
AGENTS.md
  -> guidance persistente

.skills/.agents/skills
  -> lateral-debug/design

.codex/agents
  -> reframer/verifier/implementer TOML

.codex/hooks.json
  -> UserPromptSubmit adds context
  -> PreToolUse only Bash guardrail
  -> Stop forces another pass if no validation

Optional external orchestrator
  -> Codex App Server / Codex MCP server / Agents SDK
  -> real policy engine outside Codex
```

Codex V4 no debe prometer bloqueo general de edits internos. Debe prometer:

- guidance fuerte;
- explicit subagent workflows;
- stop validation;
- Bash guardrails;
- external enforcement cuando haga falta.

## 4.4 Arquitectura externa/paritaria

Si queres paridad real Claude/Codex:

```text
Orchestrator
  -> task router
  -> workspace sandbox
  -> read-only explorers
  -> hypothesis store
  -> evaluator
  -> approval service
  -> implementation runner
  -> validation runner
  -> audit log

Adapters:
  -> Claude Agent SDK
  -> Codex App Server or Codex MCP server via Agents SDK
```

Esto es mas caro, pero es la unica ruta limpia si queres enforcement igual en ambas plataformas.

## 5. Motor cognitivo V4

## 5.1 Estado minimo

```json
{
  "schema_version": "4.0",
  "session_id": "...",
  "task_id": "...",
  "mode": "direct|lateral_lite|lateral_strict|orchestrated",
  "phase": "classified|anchored|hypotheses_ready|probes_ready|evidence_ready|converged|implemented|validated|blocked",
  "activation": {
    "score": 0,
    "reasons": [],
    "negative_reasons": []
  },
  "anchor": {
    "problem": "",
    "symptoms": [],
    "constraints": [],
    "success_criteria": []
  },
  "hypotheses": [],
  "probes": [],
  "evidence": [],
  "ranking": [],
  "winner": null,
  "implementation": {
    "files_changed": [],
    "diff_summary": ""
  },
  "validation": {
    "commands": [],
    "result": "pending|passed|failed|not_run",
    "reason_if_not_run": ""
  },
  "risks": [],
  "telemetry": {}
}
```

## 5.2 Activacion

```text
score =
  +3 if explicit_lateral_request
  +2 if ambiguous_root_cause
  +2 if cross_layer_surface
  +2 if repeated_failed_attempts >= 2
  +1 if intermittent_or_flaky
  +1 if architecture_or_design
  +1 if high_blast_radius
  -3 if localized_obvious_fix
  -2 if single_clear_stacktrace
  -2 if purely_mechanical_change
```

Reglas:

- `score >= 4` -> lateral strict en Claude, lateral lite en Codex.
- `score in [2,3]` -> lateral lite.
- `score <= 1` -> direct.
- explicit user request always activates, unless unsafe.

## 5.3 Anchor

El anchor evita drift. Debe contener:

```text
- Que se observa
- Que se sabe
- Que no se sabe
- Criterio de exito
- Restricciones de riesgo
```

Si el anchor no existe, `Edit/Write` debe bloquearse en strict mode.

## 5.4 Hipotesis

Cada hipotesis debe tener:

```json
{
  "id": "H1",
  "frame": "frontend race between optimistic update and modal close",
  "mechanism_class": "ordering_race",
  "layer": "frontend_state",
  "first_probe": "Inspect submit/close ordering and network ack path",
  "confirm_signal": "UI resets before ack",
  "falsify_signal": "Server rejects before UI state update",
  "cost": "low|medium|high",
  "risk": "low|medium|high"
}
```

### Taxonomia de hipotesis

- `contract_mismatch`
- `state_cache_staleness`
- `ordering_race_time`
- `config_env_drift`
- `schema_data_mismatch`
- `dependency_version_mismatch`
- `boundary_ownership_error`
- `hidden_business_invariant`
- `observability_gap`
- `test_harness_artifact`
- `deployment_rollout_issue`
- `security_permission_policy`

## 5.5 Diversidad util

Dos hipotesis son distintas si cambia al menos uno:

```text
mechanism_class OR layer OR first_probe OR expected_falsifier
```

Si solo cambia wording, se deduplica.

## 5.6 Probe

Un probe es bueno si:

- es read-only si todavia no convergiste;
- es barato;
- puede falsar al menos una hipotesis;
- tiene señal esperada clara;
- reduce incertidumbre real.

## 5.7 Scoring

```text
score(h) =
  0.30 * evidence_fit +
  0.25 * discriminative_power +
  0.15 * feasibility +
  0.10 * useful_novelty +
  0.10 * reversibility +
  0.05 * blast_radius_control +
  0.05 * validation_path_clarity -
  0.20 * speculation_penalty -
  0.15 * duplicate_penalty -
  0.10 * security_risk_penalty
```

Cambio frente a V3: agrego `validation_path_clarity` y `security_risk_penalty`. Una hipotesis no debe ganar si no se puede validar o si requiere permisos peligrosos sin necesidad.

## 5.8 Convergencia

```text
winner if:
  best_score >= 0.72
  and best_score - second_score >= 0.12
  and validation_path_clarity >= 0.5
```

Si no hay ganador:

1. correr un probe de desempate;
2. si sigue sin ganador, proponer instrumentacion o decision memo;
3. si el usuario necesita avance, hacer experimento reversible, no patch definitivo.

## 5.9 Early exit

Salir de lateral mode si:

- aparece causa trivial verificada;
- el usuario reduce el alcance a fix local;
- los probes muestran que las hipotesis divergen hacia falta de informacion externa;
- el costo de seguir explorando supera el blast radius del cambio.

## 5.10 Retry/reflection

Si validation falla:

```text
if same_mechanism_failed_twice:
    block new patch in same frame
    force reframe
else:
    update evidence
    rescore top-2
```

## 6. Diseño por casos de uso

| Caso | Activacion | Probes buenos | Output ideal |
|---|---|---|---|
| Debug dificil | intermitente/cross-layer | trace path, logs, targeted test, schema read | patch minimo + validation |
| Flaky test | no repro estable | run repeated test, inspect async/time/env | root cause o quarantine memo |
| Arquitectura | tradeoffs altos | compare designs, migration path, failure modes | decision memo + rollout |
| Refactor complejo | multiples cortes | dependency graph, call graph, tests surface | plan por PRs |
| Naming/API | ambiguedad semantica | grep conventions, compare domain language | decision con rationale |
| Incident response | latencia/errores | deploy diff, metrics, dependency health | mitigation first, fix later |
| Feature nueva | restricciones fuertes | compatibility, rollout, rollback, tests | design + implementation plan |

## 7. MVP V4

## 7.1 Que construir primero

**Claude Code standalone `.claude/`**, no plugin todavia.

Motivo:

- iteracion rapida;
- hooks maduros;
- gate real sobre Write/Edit;
- skills forked read-only;
- telemetria posible;
- conversion posterior a plugin.

## 7.2 Componentes MVP

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
  eval/
    fixtures/
    rubrics/
    run_eval.py
```

## 7.3 Adapter Codex MVP

```text
repo/
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
```

## 7.4 Que no entra en MVP

- MCP externo salvo docs read-only muy confiables;
- agent teams;
- GoT literal;
- fine-tuning;
- debates largos;
- dashboard completo;
- memoria long-term automatica.

## 8. Evaluacion V4

## 8.1 FAST-EVAL V4

```text
F - Functional outcome
A - Activation quality
S - Search usefulness
T - Token/latency cost
E - Evidence grounding
V - Validation discipline
A - Alternative diversity
L - Learning from failure
```

## 8.2 Metricas

| Metrica | Definicion |
|---|---|
| Resolve rate | tareas resueltas / tareas totales |
| Regret rate | casos donde lateral mode empeoro resultado |
| False activation rate | activaciones en tareas directas |
| Missed activation rate | no activo en tareas ambiguas que lo necesitaban |
| Distinct hypothesis rate | hipotesis no duplicadas / total |
| Probe usefulness | probes que cambiaron ranking / total |
| Evidence grounded winner | ganadores con evidencia real |
| Validation completion | salidas con tests/lint/typecheck/repro |
| Token multiplier | tokens lateral / tokens baseline |
| Latency multiplier | tiempo lateral / tiempo baseline |
| Developer preference | preferencia ciega baseline vs lateral |

## 8.3 Benchmark recomendado

### Offline lateral reasoning

- LatEval
- SPLAT
- BrainTeaser como smoke test

### Coding public

- SWE-bench Lite / Verified, con cautela;
- SWE-bench Pro para long horizon;
- Ambig-SWE para instrucciones subespecificadas;
- SWE-Skills-Bench para evaluar si las skills ayudan o dañan.

### Coding interno, el mas importante

Crear 80-120 tareas:

- 30 bugs ambiguos historicos;
- 20 flakes;
- 20 refactors/arquitectura;
- 10 incidentes/postmortems;
- 20 tareas simples para medir falsos positivos.

## 8.4 A/B testing

```text
baseline: Claude/Codex normal
variant A: lateral lite
variant B: lateral strict
```

Mantener igual:

- modelo;
- repo;
- permisos;
- test commands;
- contexto inicial.

Separar evaluacion de:

1. router/activacion;
2. solver cuando se activa.

## 9. Riesgos y mitigaciones

| Riesgo | Por que pasa | Deteccion | Mitigacion |
|---|---|---|---|
| Falsa diversidad | mismas ideas con distinto texto | mismos probes | dedupe por mechanism/layer/probe |
| Novelty sin valor | se premia creatividad | novelty alta, evidence baja | useful_novelty requiere probe nuevo |
| Probes malos | acciones no discriminan | ranking no cambia | probe usefulness metric |
| Convergencia prematura | top-1 elegido sin evidencia | evidence_fit bajo | threshold + tiebreak |
| No converger nunca | demasiadas ramas | rondas > cap | max rounds + memo |
| Overhead en tareas simples | router malo | false activation | negative triggers + early exit |
| Sesgo a hipotesis elegantes | LLM prefiere narrativas | speculation alto | evidence gate |
| Drift | se olvida objetivo | anchor mismatch | anchor + Stop validator |
| Seguridad MCP | tool poisoning/prompt injection | untrusted source used as instruction | least privilege + allowlists |
| State stale | memoria vieja contamina | contradice repo actual | TTL + schema version |
| Codex false enforcement | hooks no interceptan writes | edits sin state | docs honestas + external orchestrator |
| Async hook confusion | se espera que bloquee | action ya ocurrio | solo sync para policy |
| Hook permission risk | scripts corren como usuario | comandos peligrosos | small scripts, review, tests, allowlists |

## 10. Roadmap

### Semana 1

- Claude standalone `.claude/`.
- `lateral-debug` y `lateral-design`.
- state JSON atomico.
- classifier heuristico.
- PreToolUse gate para `Edit|Write`.
- Stop validator.
- 10 fixtures manuales.

### Mes 1

- PostToolUse evidence recorder.
- scorer real.
- OTel/JSONL telemetry.
- Codex adapter con `.agents/skills`, `AGENTS.md`, `.codex/agents`.
- 50-task eval interno.
- primer dashboard simple.

### Trimestre

- Claude plugin empaquetado.
- MCP read-only a CI/issues/docs.
- App Server/Agent SDK orchestrator prototype.
- multiagent solo para top tasks.
- policy tuning con datos reales.

## 11. Recomendacion final V4

La mejor arquitectura es:

- **Claude Code:** `Lateral Strict` con `.claude/` standalone primero, luego plugin.
- **Codex:** `Lateral Lite` interno + opcion `Orchestrated` externo para enforcement real.
- **Core comun:** state store, classifier, scorer, policy, telemetry y eval.

La parte que haria adentro de la plataforma:

- skills;
- hooks;
- subagents/custom agents;
- instrucciones persistentes;
- Stop validation.

La parte que haria afuera si queres producto serio multi-plataforma:

- orchestrator;
- approval service;
- durable telemetry;
- benchmark runner;
- policy audit;
- security guardrails.

Lo que descartaria por ahora:

- fine-tuning;
- debate pesado;
- agent teams por default;
- GoT literal;
- MCP amplio en MVP;
- prometer paridad Claude/Codex sin runtime externo.

La version final queda asi:

> **Un agente lateral no es un agente que piensa mas raro. Es un agente que tarda un poco mas en comprometerse cuando el problema es ambiguo, busca evidencia antes de editar, y valida antes de cerrar.**

---

# Referencias principales

## Documentacion oficial Claude Code

- Claude Code Plugins: https://code.claude.com/docs/en/plugins
- Claude Code Plugins Reference: https://code.claude.com/docs/en/plugins-reference
- Claude Code Skills: https://code.claude.com/docs/en/skills
- Claude Code Hooks: https://code.claude.com/docs/en/hooks
- Claude Code Subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Claude Agent SDK: https://code.claude.com/docs/en/agent-sdk/overview
- Claude Code Monitoring / OpenTelemetry: https://code.claude.com/docs/en/monitoring-usage
- Claude Code Channels: https://code.claude.com/docs/en/channels
- Claude system prompt / SDK customization: https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts

## Documentacion oficial Codex

- Codex AGENTS.md: https://developers.openai.com/codex/guides/agents-md
- Codex Skills: https://developers.openai.com/codex/skills
- Codex Hooks: https://developers.openai.com/codex/hooks
- Codex Subagents: https://developers.openai.com/codex/subagents
- Codex Plugins: https://developers.openai.com/codex/plugins
- Codex App Server: https://developers.openai.com/codex/app-server
- Codex MCP: https://developers.openai.com/codex/mcp
- Codex Agent approvals & security: https://developers.openai.com/codex/agent-approvals-security
- Codex with Agents SDK: https://developers.openai.com/codex/guides/agents-sdk

## Papers y benchmarks

- LatEval: https://arxiv.org/abs/2308.10855
- SPLAT: https://arxiv.org/abs/2410.06733
- Self-Consistency: https://arxiv.org/abs/2203.11171
- Tree of Thoughts: https://arxiv.org/abs/2305.10601
- Graph of Thoughts: https://arxiv.org/abs/2308.09687
- ReAct: https://arxiv.org/abs/2210.03629
- Self-Refine: https://arxiv.org/abs/2303.17651
- Reflexion: https://arxiv.org/abs/2303.11366
- Step-Back Prompting: https://arxiv.org/abs/2310.06117
- Ambig-SWE: https://arxiv.org/abs/2502.13069
- SWE-Skills-Bench: https://arxiv.org/abs/2603.15401
- Behavioral Drivers of Coding Agent Success and Failure: https://arxiv.org/abs/2604.02547
- Prompt Injection Attacks on Agentic Coding Assistants: https://arxiv.org/abs/2601.17548
- MCP Threat Modeling and Tool Poisoning: https://arxiv.org/abs/2603.22489
