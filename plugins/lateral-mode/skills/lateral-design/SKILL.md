---
description: Use for architecture, API design, refactor strategy, migration planning, or feature planning with real tradeoffs.
argument-hint: "[design problem, refactor, API, migration, or architecture decision]"
---

# Lateral Design

Use this workflow before implementation when there are meaningful design tradeoffs.

Problem:

```text
$ARGUMENTS
```

1. Anchor constraints, non-goals, success criteria, rollout constraints, and failure modes.
2. Produce 3-5 design frames that differ by mechanism, ownership boundary, rollout shape, or failure mode.
3. Compare correctness, complexity, rollout, reversibility, observability, security, and validation.
4. Choose a winner and record it with `lateral-mode checkpoint --json ...`.
5. Keep the first implementation minimal and reversible.
