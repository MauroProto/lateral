# Changelog

## 0.2.0 - 2026-05-13

### Added

- Added a self-contained Claude Code plugin bundle at `plugins/lateral-mode`.
- Added local Claude marketplace metadata at `.claude-plugin/marketplace.json`.
- Added plugin-scoped `lateral-mode` control binary.
- Added `lateral report` for measurement summaries.

### Changed

- `lateral reset` now resets the effective local/global state instead of always
  writing repo-local `.lateral/state.json`.
- Stop hooks now avoid recursive blocking when `stop_hook_active` is true.

## 0.1.0 - 2026-05-12

### Added

- Added local/plugin-controlled Lateral Mode MVP.
- Added router fixtures and gate tests for simple vs ambiguous tasks.
- Added CLI controls, checkpointing, telemetry metrics, and outcome recording.
