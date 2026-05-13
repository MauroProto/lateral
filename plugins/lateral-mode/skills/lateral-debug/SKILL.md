---
description: Use for ambiguous, intermittent, cross-layer, flaky, or repeatedly failing bugs. Do not use for obvious localized fixes.
argument-hint: "[bug, symptom, failing test, incident, or ambiguous behavior]"
---

# Lateral Debug

Use this workflow before editing ambiguous bug fixes.

Issue:

```text
$ARGUMENTS
```

1. Anchor the problem: symptoms, facts, unknowns, success criteria, and risk constraints.
2. Generate 3-5 materially distinct hypotheses.
3. Give each hypothesis an id, mechanism class, layer, first probe, confirm signal, falsify signal, cost, and risk.
4. Prefer cheap read-only probes before implementation.
5. Rank the top two hypotheses by evidence, discriminative power, feasibility, reversibility, and validation clarity.
6. Record convergence before editing:

```bash
lateral-mode checkpoint --json '{"anchor":{"problem":"...","success_criteria":["..."]},"hypotheses":[{"id":"H1","mechanism_class":"...","layer":"...","first_probe":"..."},{"id":"H2","mechanism_class":"...","layer":"...","first_probe":"..."}],"winner":"H1"}'
```

After implementation, record validation with:

```bash
lateral-mode checkpoint --json '{"validation":{"commands":["..."],"result":"passed","reason_if_not_run":""}}'
```
