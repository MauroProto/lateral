# lateral-mode Claude Code Plugin

`lateral-mode` is a Claude Code plugin that adds a local gate for ambiguous
coding tasks.

It keeps simple edits direct, but asks Claude to slow down on ambiguous bugs,
cross-layer failures, incidents, flaky tests, and risky design work.

The enforced loop is:

```text
anchor -> hypotheses -> probes -> evidence -> convergence -> edit -> validation
```

## Components

- Skills:
  - `/lateral-mode:lateral-debug`
  - `/lateral-mode:lateral-design`
  - `/lateral-mode:lateral-control`
- Subagents:
  - `lateral-mode:reframer`
  - `lateral-mode:verifier`
- Hooks:
  - `UserPromptSubmit`
  - `PreToolUse`
  - `Stop`
- Binary:
  - `lateral-mode`

## Run Locally

From the repository root:

```bash
claude --plugin-dir ./plugins/lateral-mode
```

Inside Claude Code:

```text
/reload-plugins
/lateral-mode:lateral-control status
/lateral-mode:lateral-debug Sometimes checkout succeeds but payment is missing later
```

## Install from the Local Marketplace

From the repository root:

```bash
claude plugin marketplace add .
claude plugin install lateral-mode@lateral-local
```

## Commands

When the plugin is active, Claude can use:

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
lateral-mode outcome --resolved yes --rating 4 --validation passed
```

Record a strict-mode checkpoint:

```bash
lateral-mode checkpoint --json '{"anchor":{"problem":"...","success_criteria":["..."]},"hypotheses":[{"id":"H1","mechanism_class":"...","layer":"...","first_probe":"..."},{"id":"H2","mechanism_class":"...","layer":"...","first_probe":"..."}],"winner":"H1"}'
```

## State

The plugin is self-contained:

- hook scripts use `${CLAUDE_PLUGIN_ROOT}`
- durable state lives in `${CLAUDE_PLUGIN_DATA}/.lateral/`
- the Python engine is vendored under `vendor/lateral/`
- repositories are not modified just because the plugin is active

## Validation

```bash
claude plugin validate ./plugins/lateral-mode
claude plugin validate .
```

The parent repository also provides:

```bash
make verify
```

## Troubleshooting

If the plugin does not load:

```bash
claude plugin validate ./plugins/lateral-mode
claude --debug --plugin-dir ./plugins/lateral-mode
```

If the gate is too intrusive:

```bash
lateral-mode off
```
