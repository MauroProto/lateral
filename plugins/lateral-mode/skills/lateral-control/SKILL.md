---
description: Control and inspect Lateral Mode. Use when the user asks to enable, disable, inspect, reset, or measure lateral mode.
argument-hint: "on | off | auto | lite | strict | status | metrics | report"
disable-model-invocation: true
---

# Lateral Control

Requested control:

```text
$ARGUMENTS
```

Use the local plugin command:

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

Use `lateral-mode outcome` after real work to measure usefulness:

```bash
lateral-mode outcome --resolved yes --rating 4 --validation passed
lateral-mode outcome --resolved no --rating 2 --validation failed --notes "wrong hypothesis"
```
