# Lateral Mode

Lateral Mode is a local workflow gate for coding agents.

It does not try to make an LLM "more creative" by magic. It adds a practical
guardrail: when a task looks ambiguous, intermittent, cross-layer, or risky, the
agent must slow down, form multiple hypotheses, gather cheap evidence, converge,
and validate before it edits or closes the task.

For simple work, it stays out of the way.

## Why This Exists

Coding agents often fail on ambiguous bugs for the same reason humans do:
they commit too early to the first plausible explanation.

Lateral Mode turns that into an explicit local loop:

```text
anchor -> hypotheses -> probes -> evidence -> convergence -> edit -> validation
```

The MVP goal is intentionally narrow:

- do not add friction to obvious tasks
- activate on ambiguous bugs and incidents
- block premature edits only in strict mode
- measure whether the workflow helped in real sessions

## What It Provides

- A Python CLI named `lateral`
- A self-contained Claude Code plugin at `plugins/lateral-mode`
- A local Claude Code marketplace at `.claude-plugin/marketplace.json`
- Claude Code skills for debugging, design, and control
- Claude Code subagents for reframing and verification
- Claude Code hooks for prompt classification, pre-tool gating, and stop checks
- Local telemetry for activations, blocks, validation, and human outcomes
- Synthetic eval fixtures for router and gate regression testing

## Repository Layout

```text
.
├── lateral/                         # Python engine and CLI
├── plugins/lateral-mode/            # Claude Code plugin bundle
│   ├── .claude-plugin/plugin.json   # Plugin manifest
│   ├── skills/                      # Claude Code skills
│   ├── agents/                      # Claude Code subagents
│   ├── hooks/hooks.json             # Claude Code hook config
│   ├── scripts/lateral_hook.py      # Plugin hook entrypoint
│   ├── bin/lateral-mode             # Plugin control command
│   └── vendor/lateral/              # Vendored engine for self-contained plugin use
├── .claude-plugin/marketplace.json  # Local marketplace manifest
├── eval/fixtures/                   # Router and gate eval fixtures
├── tests/                           # Unit and integration tests
└── Makefile                         # Verification commands
```

## Install for Local Development

```bash
python3 -m pip install -e .
```

Check the CLI:

```bash
lateral status --path .
lateral eval-suite \
  --fixtures eval/fixtures/mvp_tasks.json \
  --fixtures eval/fixtures/robust_router_tasks.json \
  --fixtures eval/fixtures/stress_router_tasks.json
```

## Use as a Claude Code Plugin

Run the plugin directly without installing it:

```bash
claude --plugin-dir ./plugins/lateral-mode
```

Inside Claude Code, the plugin exposes:

```text
/lateral-mode:lateral-debug
/lateral-mode:lateral-design
/lateral-mode:lateral-control
```

It also exposes a command available to Claude's Bash tool:

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

## Install from the Local Marketplace

From this repository root:

```bash
claude plugin marketplace add .
claude plugin install lateral-mode@lateral-local
```

Then reload plugins inside Claude Code:

```text
/reload-plugins
```

Validate the plugin and marketplace:

```bash
claude plugin validate ./plugins/lateral-mode
claude plugin validate .
```

## Modes

### `off`

No lateral behavior.

```bash
lateral off --path /path/to/repo
lateral-mode off
```

### `auto`

Default mode. The classifier decides whether a prompt is direct, lite, or
strict.

```bash
lateral mode auto --path /path/to/repo
lateral-mode auto
```

### `lite`

Injects lateral guidance, but does not block edits.

```bash
lateral mode lite --path /path/to/repo
lateral-mode lite
```

### `strict`

Blocks premature edits on ambiguous tasks until a checkpoint records:

- an anchor
- at least two materially distinct hypotheses
- a probe for each hypothesis
- a converged winning hypothesis

```bash
lateral mode strict --path /path/to/repo
lateral-mode strict
```

## Hook Behavior

The Claude Code plugin installs three hooks:

### `UserPromptSubmit`

Classifies each prompt and injects lateral guidance only when useful.

Control prompts are also supported:

```text
lateral on
lateral off
lateral auto
lateral lite
lateral strict
lateral status
```

### `PreToolUse`

Blocks risky Bash commands and, in strict mode, blocks premature writes through
tools such as `Edit`, `Write`, and `MultiEdit`.

Examples of blocked Bash patterns:

```text
rm -rf /
git push --force
curl ... | sh
wget ... | bash
```

### `Stop`

Prevents the agent from ending a lateral session without validation or an
explicit reason validation was not possible. The stop hook also handles
`stop_hook_active` so it does not create recursive stop loops.

## Recording a Checkpoint

When strict mode blocks editing, the agent should record convergence:

```bash
lateral checkpoint --path /path/to/repo --json '{
  "anchor": {
    "problem": "Checkout sometimes succeeds but payment is missing later",
    "success_criteria": ["payment status is consistent across UI, API, and webhook logs"]
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

With the Claude plugin active, the shorter form is:

```bash
lateral-mode checkpoint --json '{"anchor":{"problem":"..."},"hypotheses":[...],"winner":"H1"}'
```

## Measuring Whether It Helps

Lateral Mode records local JSONL events:

- prompt classifications
- lateral activations
- denied pre-tool calls
- stop blocks
- human outcome ratings

Record an outcome after real work:

```bash
lateral outcome --path /path/to/repo --resolved yes --rating 5 --validation passed
lateral outcome --path /path/to/repo --resolved no --rating 2 --validation failed --notes "wrong hypothesis"
```

With the plugin:

```bash
lateral-mode outcome --resolved yes --rating 4 --validation passed
```

Inspect metrics:

```bash
lateral metrics --path /path/to/repo
lateral report --path /path/to/repo
lateral report --path /path/to/repo --json
```

Example report fields:

```json
{
  "user_prompts": 10,
  "lateral_activations": 3,
  "activation_rate": 0.3,
  "pre_tool_denies": 1,
  "stop_blocks": 1,
  "outcomes": 4,
  "resolve_rate": 0.75,
  "average_rating": 4.25
}
```

## Real Evaluation Protocol

Synthetic routing tests are necessary, but they do not prove product value.

To test whether Lateral Mode actually helps:

1. Collect 20-50 real coding tasks.
2. Split them into simple tasks and ambiguous bugs/incidents/refactors.
3. Run a baseline with normal agent behavior.
4. Run the same task class with `lateral-mode auto`.
5. Record outcome after every task:
   - resolved: yes/no
   - rating: 1-5
   - validation: passed/failed/not_run/not_applicable
   - notes: friction, wrong hypothesis, or useful probe
6. Compare:
   - resolution rate
   - time to fix
   - validation rate
   - false activations on simple tasks
   - missed activations on ambiguous tasks
   - user friction

The current MVP has strong synthetic and packaging validation. It still needs
real historical bug-fix evaluation before claiming it improves production
outcomes.

## Verification

Run the full local verification suite:

```bash
make verify
```

The verification target runs:

- unit and integration tests
- built-in eval
- fixture eval suite
- Python compilation checks
- Claude plugin manifest validation
- Claude marketplace validation
- temporary virtualenv package smoke test
- artifact cleanup

You can run smaller checks directly:

```bash
python3 -m unittest discover -s tests -v
python3 -m lateral eval-suite \
  --fixtures eval/fixtures/mvp_tasks.json \
  --fixtures eval/fixtures/robust_router_tasks.json \
  --fixtures eval/fixtures/stress_router_tasks.json
claude plugin validate ./plugins/lateral-mode
claude plugin validate .
```

## Security and Privacy

- No secrets are required.
- No remote service is required.
- State is local.
- The Claude Code plugin stores durable state in `${CLAUDE_PLUGIN_DATA}/.lateral/`.
- Global CLI install stores state in `~/.lateral/`.
- Uninitialized repositories are not modified just because the global/plugin hook runs.
- Risky shell bootstrap patterns such as `curl | sh` are blocked.

## Troubleshooting

### The plugin does not appear

```bash
claude plugin validate ./plugins/lateral-mode
claude --plugin-dir ./plugins/lateral-mode
```

Inside Claude Code:

```text
/reload-plugins
/plugin
```

### Skills do not appear

Check that the skill files live here:

```text
plugins/lateral-mode/skills/<skill-name>/SKILL.md
```

They must not be placed inside `.claude-plugin/`.

### Hooks do not fire

Run Claude Code in debug mode:

```bash
claude --debug --plugin-dir ./plugins/lateral-mode
```

Check:

- `plugins/lateral-mode/hooks/hooks.json`
- `plugins/lateral-mode/scripts/lateral_hook.py`
- executable permissions on `scripts/lateral_hook.py`

### The gate is too intrusive

```bash
lateral-mode off
```

or:

```bash
lateral off --path /path/to/repo
```

## License

MIT. See [LICENSE](LICENSE).
