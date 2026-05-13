# Lateral Mode

Lateral Mode is a local Claude Code plugin and Python CLI that helps coding
agents avoid premature edits on ambiguous work.

It keeps simple tasks fast. When a prompt looks like an intermittent bug,
cross-layer failure, incident, flaky test, or risky design decision, it asks the
agent to anchor the problem, generate distinct hypotheses, gather cheap
evidence, converge, and validate.

```text
anchor -> hypotheses -> probes -> evidence -> convergence -> edit -> validation
```

## Install

One command:

```bash
curl -fsSL https://raw.githubusercontent.com/MauroProto/lateral/main/install.sh -o /tmp/lateral-install.sh && bash /tmp/lateral-install.sh
```

The installer:

- clones or updates the repo at `~/.lateral-mode/source`
- creates a private Python venv at `~/.lateral-mode/venv`
- installs the `lateral` CLI
- symlinks it to `~/.local/bin/lateral`
- validates the Claude Code plugin
- registers the local marketplace
- installs `lateral-mode@lateral-local` when Claude Code is available

Manual install:

```bash
git clone https://github.com/MauroProto/lateral.git
cd lateral
python3 -m pip install -e .
claude plugin marketplace add .
claude plugin install lateral-mode@lateral-local
```

Run without installing the plugin:

```bash
claude --plugin-dir ./plugins/lateral-mode
```

## What It Adds

### Claude Code plugin

Plugin bundle:

```text
plugins/lateral-mode/
```

Available skills:

```text
/lateral-mode:lateral-debug
/lateral-mode:lateral-design
/lateral-mode:lateral-control
```

Available plugin agents:

```text
lateral-mode:reframer
lateral-mode:verifier
```

Available command inside Claude's Bash tool:

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

### Python CLI

```bash
lateral status --path .
lateral mode strict --path .
lateral checkpoint --path . --json '{"anchor":{"problem":"..."},"hypotheses":[...],"winner":"H1"}'
lateral outcome --path . --resolved yes --rating 4 --validation passed
lateral report --path .
```

## Modes

| Mode | Behavior |
| --- | --- |
| `off` | No lateral behavior. |
| `auto` | Default. Classifies each prompt and activates only when useful. |
| `lite` | Adds lateral guidance but does not block edits. |
| `strict` | Blocks premature edits until the agent records anchor, hypotheses, probes, and convergence. |

## How the Gate Works

The Claude Code plugin installs three hooks:

| Hook | Purpose |
| --- | --- |
| `UserPromptSubmit` | Classifies the prompt and injects lateral context only when needed. |
| `PreToolUse` | Blocks risky Bash commands and premature writes in strict mode. |
| `Stop` | Requires validation or an explicit validation exception before closing lateral work. |

Strict mode allows writes only after a checkpoint with:

- a clear problem anchor
- at least two materially distinct hypotheses
- a cheap probe for each hypothesis
- a winning hypothesis or convergence decision

Example checkpoint:

```bash
lateral-mode checkpoint --json '{
  "anchor": {
    "problem": "Checkout sometimes succeeds but payment is missing later",
    "success_criteria": ["UI, API, and webhook state agree"]
  },
  "hypotheses": [
    {
      "id": "H1",
      "mechanism_class": "webhook_delivery",
      "layer": "integration",
      "first_probe": "inspect webhook delivery logs for missing event ids"
    },
    {
      "id": "H2",
      "mechanism_class": "state_race",
      "layer": "backend",
      "first_probe": "trace payment status writes around checkout completion"
    }
  ],
  "winner": "H1"
}'
```

## Measurement

Lateral Mode records local JSONL telemetry for:

- prompt classifications
- lateral activations
- denied pre-tool calls
- stop blocks
- human outcome ratings

Record real outcomes:

```bash
lateral-mode outcome --resolved yes --rating 5 --validation passed
lateral-mode outcome --resolved no --rating 2 --validation failed --notes "wrong hypothesis"
```

Inspect results:

```bash
lateral-mode metrics
lateral-mode report
lateral-mode report --json
```

The current MVP is validated against synthetic fixtures and packaging smoke
tests. It does not yet prove higher real-world bug resolution. Use `outcome`
records across 20-50 real tasks to compare baseline agent behavior against
`lateral-mode auto`.

## Project Layout

```text
.
├── install.sh                       # one-command installer
├── lateral/                         # Python engine and CLI
├── plugins/lateral-mode/            # Claude Code plugin bundle
├── .claude-plugin/marketplace.json  # local Claude plugin marketplace
├── eval/fixtures/                   # router and gate eval fixtures
├── tests/                           # unit and integration tests
└── Makefile                         # verification entrypoint
```

## Verification

```bash
make verify
```

This runs:

- Python unit and integration tests
- router evals
- fixture eval suite
- Python compilation checks
- `claude plugin validate ./plugins/lateral-mode`
- `claude plugin validate .`
- package install smoke test in a temporary venv
- cleanup of generated artifacts

Focused checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m lateral eval-suite \
  --fixtures eval/fixtures/mvp_tasks.json \
  --fixtures eval/fixtures/robust_router_tasks.json \
  --fixtures eval/fixtures/stress_router_tasks.json
claude plugin validate ./plugins/lateral-mode
claude plugin validate .
```

## Safety and Privacy

- No secrets are required.
- No remote service is required.
- Plugin state is stored locally in `${CLAUDE_PLUGIN_DATA}/.lateral/`.
- CLI global state is stored locally in `~/.lateral/`.
- Repositories are not modified just because the plugin hook runs.
- Risky commands such as `rm -rf /`, `git push --force`, and `curl ... | sh`
  are blocked by the hook.

## Troubleshooting

### `lateral` is not found

The installer symlinks the CLI to `~/.local/bin/lateral`. Add this directory to
your shell `PATH` if needed:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Claude plugin does not appear

```bash
claude plugin validate ./plugins/lateral-mode
claude plugin validate .
claude --plugin-dir ./plugins/lateral-mode
```

Inside Claude Code:

```text
/reload-plugins
/plugin
```

### The gate is too intrusive

```bash
lateral-mode off
```

or:

```bash
lateral off --path .
```

## License

MIT. See [LICENSE](LICENSE).
