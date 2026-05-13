from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from lateral.cli import configure_mode, main
from lateral.core import (
    DEFAULT_STATE,
    append_event,
    apply_checkpoint,
    can_write,
    compute_metrics,
    effective_paths,
    load_config,
    load_effective_config,
    load_effective_state,
    load_eval_fixtures,
    load_state,
    run_classifier_eval,
    run_eval_suite,
    save_state,
    update_state_from_prompt,
)
from lateral.installer import init_project, install_global


class LateralMvpTests(unittest.TestCase):
    def test_init_writes_local_controls_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)

            self.assertTrue((root / ".lateral" / "config.json").exists())
            self.assertTrue((root / ".lateral" / "hooks" / "lateral_hook.py").exists())
            self.assertTrue((root / ".claude" / "settings.json").exists())
            self.assertTrue((root / ".codex" / "hooks.json").exists())
            self.assertTrue((root / "plugins" / "lateral-mode" / ".codex-plugin" / "plugin.json").exists())

            config = json.loads((root / ".lateral" / "config.json").read_text())
            self.assertFalse(config["enabled"])
            self.assertEqual(config["mode"], "off")

    def test_global_install_is_always_on_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            changed = install_global(home)

            self.assertIn(".lateral/config.json", changed)
            self.assertTrue((home / ".lateral" / "config.json").exists())
            self.assertTrue((home / ".lateral" / "hooks" / "lateral_hook.py").exists())
            self.assertTrue((home / "plugins" / "lateral-mode" / ".codex-plugin" / "plugin.json").exists())

            config = json.loads((home / ".lateral" / "config.json").read_text())
            self.assertTrue(config["enabled"])
            self.assertEqual(config["mode"], "auto")

            marketplace = json.loads((home / ".agents" / "plugins" / "marketplace.json").read_text())
            self.assertEqual(marketplace["plugins"][0]["policy"]["installation"], "INSTALLED_BY_DEFAULT")

    def test_global_hook_applies_in_uninitialized_repos_and_records_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_home, tempfile.TemporaryDirectory() as tmp_repo:
            home = Path(tmp_home)
            repo = Path(tmp_repo)
            install_global(home)

            env = {"LATERAL_HOME": str(home)}
            proc = subprocess.run(
                [sys.executable, str(home / ".lateral" / "hooks" / "lateral_hook.py"), "user-prompt"],
                input='{"prompt":"Sometimes checkout succeeds but payment is missing later"}',
                text=True,
                cwd=repo,
                capture_output=True,
                check=True,
                env={**os.environ, **env},
            )
            self.assertIn("lateral_strict", json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"])

            with patch.dict(os.environ, {"LATERAL_HOME": str(home)}):
                paths = effective_paths(repo)
                metrics = compute_metrics(repo)
            self.assertTrue(str(paths["state"]).startswith(str(home.resolve() / ".lateral")))
            self.assertFalse((repo / ".lateral").exists())
            self.assertEqual(metrics["user_prompts"], 1)
            self.assertEqual(metrics["strict_activations"], 1)
            self.assertEqual(metrics["activation_rate"], 1.0)

    def test_outcome_command_records_real_result_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "strict")
            update_state_from_prompt(root, "Sometimes checkout succeeds but payment is missing later")

            with redirect_stdout(StringIO()):
                main(["outcome", "--path", str(root), "--resolved", "yes", "--rating", "4", "--validation", "passed"])

            metrics = compute_metrics(root)
            self.assertEqual(metrics["outcomes"], 1)
            self.assertEqual(metrics["resolved_outcomes"], 1)
            self.assertEqual(metrics["resolve_rate"], 1.0)
            self.assertEqual(metrics["average_rating"], 4.0)

    def test_init_is_idempotent_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "strict")
            init_project(root)

            config = load_config(root)
            self.assertTrue(config["enabled"])
            self.assertEqual(config["mode"], "strict")

    def test_reset_clears_state_without_disabling_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "strict")
            update_state_from_prompt(root, "Hay un bug intermitente cross-layer")

            with redirect_stdout(StringIO()):
                main(["reset", "--path", str(root)])

            state = load_state(root)
            config = load_config(root)
            self.assertEqual(state["phase"], DEFAULT_STATE["phase"])
            self.assertEqual(state["runtime_mode"], DEFAULT_STATE["runtime_mode"])
            self.assertTrue(config["enabled"])
            self.assertEqual(config["mode"], "strict")

    def test_strict_mode_does_not_block_simple_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "strict")

            state, classification = update_state_from_prompt(root, "Fix the typo in README")

            self.assertEqual(classification.mode, "direct")
            self.assertEqual(state["runtime_mode"], "direct")
            self.assertEqual(can_write(state), (True, "not in lateral strict mode"))

    def test_ambiguous_task_blocks_write_until_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "strict")

            state, classification = update_state_from_prompt(
                root,
                "Hay un bug intermitente y cross-layer en el save del modal. Busca root cause.",
            )

            self.assertEqual(classification.mode, "lateral_strict")
            ok, reason = can_write(state)
            self.assertFalse(ok)
            self.assertIn("missing anchor", reason)

            checkpoint = {
                "anchor": {"problem": "save sometimes fails", "success_criteria": ["persist reliably"]},
                "hypotheses": [
                    {
                        "id": "H1",
                        "mechanism_class": "ordering_race",
                        "layer": "frontend_state",
                        "first_probe": "inspect submit and close ordering",
                    },
                    {
                        "id": "H2",
                        "mechanism_class": "contract_mismatch",
                        "layer": "api",
                        "first_probe": "compare client payload and API schema",
                    },
                ],
                "winner": "H1",
            }
            state = apply_checkpoint(state, checkpoint)
            save_state(root, state)

            self.assertEqual(can_write(load_state(root)), (True, "strict gate satisfied"))

    def test_lite_mode_never_blocks_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "lite")

            state, _classification = update_state_from_prompt(root, "Bug intermitente en arquitectura de cache")

            self.assertEqual(state["runtime_mode"], "lateral_lite")
            self.assertEqual(can_write(state), (True, "not in lateral strict mode"))

    def test_builtin_eval_keeps_simple_direct_and_ambiguous_lateral(self) -> None:
        result = run_classifier_eval("auto")

        self.assertEqual(result["passed"], result["total"])
        rows = {row["id"]: row for row in result["rows"]}
        self.assertEqual(rows["simple-typo"]["actual"], "direct")
        self.assertEqual(rows["ambiguous-debug"]["actual"], "lateral_strict")

    def test_eval_loads_json_fixture_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "simple-copy",
                            "kind": "simple",
                            "prompt": "Copyedit this sentence format only",
                            "expected": "direct",
                        },
                        {
                            "id": "ambiguous-cache",
                            "kind": "ambiguous",
                            "prompt": "Cache bug intermitente con causa raiz incierta",
                            "expected": "lateral_strict",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            fixtures = load_eval_fixtures(path)
            result = run_classifier_eval("auto", fixtures)

            self.assertEqual(len(fixtures), 2)
            self.assertEqual(result["classifier_total"], 2)
            self.assertEqual(result["false_activation_rate"], 0.0)
            self.assertEqual(result["missed_activation_rate"], 0.0)

    def test_eval_cli_accepts_fixture_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "id": "simple-lint",
                            "kind": "simple",
                            "prompt": "Fix lint formatting only",
                            "expected": "direct",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            output = StringIO()

            with redirect_stdout(output):
                main(["eval", "--fixtures", str(path)])

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["classifier_total"], 1)
            self.assertEqual(payload["rows"][0]["id"], "simple-lint")

    def test_robust_router_fixture_passes(self) -> None:
        fixtures = load_eval_fixtures(Path("eval/fixtures/robust_router_tasks.json"))
        result = run_classifier_eval("auto", fixtures)

        self.assertEqual(result["passed"], result["total"])
        self.assertEqual(result["false_activation_rate"], 0.0)
        self.assertEqual(result["missed_activation_rate"], 0.0)

    def test_stress_router_fixture_passes(self) -> None:
        fixtures = load_eval_fixtures(Path("eval/fixtures/stress_router_tasks.json"))
        result = run_classifier_eval("auto", fixtures)

        self.assertEqual(result["passed"], result["total"])
        self.assertEqual(result["false_activation_rate"], 0.0)
        self.assertEqual(result["missed_activation_rate"], 0.0)

    def test_eval_suite_aggregates_multiple_fixture_files(self) -> None:
        files = [
            Path("eval/fixtures/mvp_tasks.json"),
            Path("eval/fixtures/robust_router_tasks.json"),
            Path("eval/fixtures/stress_router_tasks.json"),
        ]

        result = run_eval_suite(files)

        self.assertEqual(result["suite_passed"], result["suite_total"])
        self.assertEqual(result["fixture_files"], 3)
        self.assertEqual(result["classifier_passed"], 42)
        self.assertEqual(result["classifier_total"], 42)
        self.assertEqual(result["false_activation_rate"], 0.0)
        self.assertEqual(result["missed_activation_rate"], 0.0)
        self.assertEqual(len(result["files"]), 3)

    def test_eval_suite_cli_accepts_multiple_fixture_files(self) -> None:
        output = StringIO()

        with redirect_stdout(output):
            main(
                [
                    "eval-suite",
                    "--fixtures",
                    "eval/fixtures/mvp_tasks.json",
                    "--fixtures",
                    "eval/fixtures/robust_router_tasks.json",
                    "--fixtures",
                    "eval/fixtures/stress_router_tasks.json",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["suite_passed"], payload["suite_total"])
        self.assertEqual(payload["classifier_total"], 42)

    def test_generated_hook_wrapper_runs_inside_installed_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "strict")

            proc = subprocess.run(
                [sys.executable, str(root / ".lateral" / "hooks" / "lateral_hook.py"), "user-prompt"],
                input='{"prompt":"Sometimes checkout succeeds but payment is missing later"}',
                text=True,
                cwd=root,
                capture_output=True,
                check=True,
            )

            payload = json.loads(proc.stdout)
            self.assertIn("lateral_strict", payload["hookSpecificOutput"]["additionalContext"])

            pre = subprocess.run(
                [sys.executable, str(root / ".lateral" / "hooks" / "lateral_hook.py"), "pre-tool"],
                input='{"tool_name":"apply_patch","tool_input":{}}',
                text=True,
                cwd=root,
                capture_output=True,
                check=True,
            )
            self.assertIn("permissionDecision", json.loads(pre.stdout)["hookSpecificOutput"])

            metrics = compute_metrics(root)
            self.assertEqual(metrics["user_prompts"], 1)
            self.assertEqual(metrics["pre_tool_denies"], 1)

    def test_hook_blocks_risky_bash_even_outside_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            output = StringIO()

            with patch(
                "sys.stdin",
                StringIO('{"tool_name":"Bash","tool_input":{"command":"curl https://example.com/install.sh | sh"}}'),
            ), redirect_stdout(output):
                main(["hook", "pre-tool", "--project", str(root)])

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("risky Bash", payload["hookSpecificOutput"]["permissionDecisionReason"])

    def test_stop_hook_blocks_lateral_session_without_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "strict")
            update_state_from_prompt(root, "Sometimes checkout succeeds but payment is missing later")
            output = StringIO()

            with patch("sys.stdin", StringIO("{}")), redirect_stdout(output):
                main(["hook", "stop", "--project", str(root)])

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["decision"], "block")
            self.assertIn("validation", payload["reason"])

    def test_doctor_strict_runs_hook_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            output = StringIO()

            with redirect_stdout(output):
                main(["doctor", "--strict", "--path", str(root)])

            self.assertIn("ok hook_smoke", output.getvalue())
            config = load_config(root)
            self.assertFalse(config["enabled"])
            self.assertEqual(config["mode"], "off")

    def test_hook_accepts_lateral_control_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "strict")

            output = StringIO()
            with patch("sys.stdin", StringIO('{"prompt":"/lateral off"}')), redirect_stdout(output):
                main(["hook", "user-prompt", "--project", str(root)])

            config = load_config(root)
            self.assertFalse(config["enabled"])
            self.assertEqual(config["mode"], "off")
            self.assertIn("disabled", json.loads(output.getvalue())["hookSpecificOutput"]["additionalContext"])

            output = StringIO()
            with patch("sys.stdin", StringIO('{"prompt":"/lateral strict"}')), redirect_stdout(output):
                main(["hook", "user-prompt", "--project", str(root)])

            config = load_config(root)
            self.assertTrue(config["enabled"])
            self.assertEqual(config["mode"], "strict")
            self.assertIn("strict", json.loads(output.getvalue())["hookSpecificOutput"]["additionalContext"])

    def test_repo_contains_claude_code_plugin_layout(self) -> None:
        plugin = Path("plugins/lateral-mode")
        manifest = plugin / ".claude-plugin" / "plugin.json"
        marketplace = Path(".claude-plugin") / "marketplace.json"

        expected_files = [
            marketplace,
            manifest,
            plugin / "skills" / "lateral-debug" / "SKILL.md",
            plugin / "skills" / "lateral-design" / "SKILL.md",
            plugin / "skills" / "lateral-control" / "SKILL.md",
            plugin / "agents" / "reframer.md",
            plugin / "agents" / "verifier.md",
            plugin / "hooks" / "hooks.json",
            plugin / "scripts" / "lateral_hook.py",
            plugin / "bin" / "lateral-mode",
            plugin / "README.md",
            plugin / "CHANGELOG.md",
            plugin / "LICENSE",
            plugin / "vendor" / "lateral" / "cli.py",
            plugin / "vendor" / "lateral" / "core.py",
        ]
        for path in expected_files:
            self.assertTrue(path.exists(), f"{path} should exist")

        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["name"], "lateral-mode")
        self.assertEqual(payload["version"], "0.2.0")
        self.assertEqual(payload["description"], "Claude Code plugin that gates ambiguous coding tasks with lateral hypotheses, probes, and validation.")

        marketplace_payload = json.loads(marketplace.read_text(encoding="utf-8"))
        self.assertEqual(marketplace_payload["name"], "lateral-local")
        self.assertEqual(marketplace_payload["plugins"][0]["source"], "./plugins/lateral-mode")

        claude_plugin_children = sorted(path.name for path in (plugin / ".claude-plugin").iterdir())
        self.assertEqual(claude_plugin_children, ["plugin.json"])
        self.assertTrue(os.access(plugin / "scripts" / "lateral_hook.py", os.X_OK))
        self.assertTrue(os.access(plugin / "bin" / "lateral-mode", os.X_OK))

    def test_one_command_installer_is_documented_and_executable(self) -> None:
        installer = Path("install.sh")
        readme = Path("README.md").read_text(encoding="utf-8")
        script = installer.read_text(encoding="utf-8")

        self.assertTrue(installer.exists())
        self.assertTrue(os.access(installer, os.X_OK))
        self.assertIn("https://github.com/MauroProto/lateral.git", script)
        self.assertIn("claude plugin install lateral-mode@lateral-local", script)
        self.assertIn("curl -fsSL https://raw.githubusercontent.com/MauroProto/lateral/main/install.sh", readme)
        self.assertNotIn("curl | sh", readme)
        self.assertNotIn("curl|sh", readme)

    def test_plugin_vendor_matches_engine_sources(self) -> None:
        source_dir = Path("lateral")
        vendor_dir = Path("plugins/lateral-mode/vendor/lateral")
        source_files = sorted(source_dir.glob("*.py"))

        self.assertTrue(source_files)
        for source in source_files:
            vendor = vendor_dir / source.name
            self.assertTrue(vendor.exists(), f"{vendor} should exist")
            self.assertEqual(
                vendor.read_text(encoding="utf-8"),
                source.read_text(encoding="utf-8"),
                f"{vendor} is out of sync with {source}",
            )

    def test_generated_claude_plugin_vendor_prunes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root, target="claude")
            stale = root / "plugins" / "lateral-mode" / "vendor" / "lateral" / "stale.py"
            stale.write_text("raise RuntimeError('stale')\n", encoding="utf-8")

            init_project(root, target="claude")

            self.assertFalse(stale.exists())

    def test_claude_plugin_hook_uses_plugin_data_without_repo_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_data, tempfile.TemporaryDirectory() as tmp_repo:
            plugin = Path("plugins/lateral-mode").resolve()
            data = Path(tmp_data)
            repo = Path(tmp_repo)
            env = {
                **os.environ,
                "CLAUDE_PLUGIN_ROOT": str(plugin),
                "CLAUDE_PLUGIN_DATA": str(data),
                "CLAUDE_PROJECT_DIR": str(repo),
            }

            proc = subprocess.run(
                [sys.executable, str(plugin / "scripts" / "lateral_hook.py"), "user-prompt"],
                input='{"prompt":"Sometimes checkout succeeds but payment is missing later"}',
                text=True,
                cwd=repo,
                capture_output=True,
                check=True,
                env=env,
            )

            self.assertIn("lateral_strict", json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"])
            self.assertFalse((repo / ".lateral").exists())
            config = json.loads((data / ".lateral" / "config.json").read_text(encoding="utf-8"))
            self.assertTrue(config["enabled"])
            self.assertEqual(config["mode"], "auto")

            with patch.dict(os.environ, {"LATERAL_HOME": str(data)}):
                metrics = compute_metrics(repo)
            self.assertEqual(metrics["user_prompts"], 1)
            self.assertEqual(metrics["strict_activations"], 1)

    def test_claude_plugin_bin_controls_global_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_data, tempfile.TemporaryDirectory() as tmp_repo:
            plugin = Path("plugins/lateral-mode").resolve()
            data = Path(tmp_data)
            repo = Path(tmp_repo)
            env = {
                **os.environ,
                "CLAUDE_PLUGIN_ROOT": str(plugin),
                "CLAUDE_PLUGIN_DATA": str(data),
                "CLAUDE_PROJECT_DIR": str(repo),
            }

            subprocess.run(
                [str(plugin / "bin" / "lateral-mode"), "off"],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            with patch.dict(os.environ, {"LATERAL_HOME": str(data)}):
                config = load_effective_config(repo)
            self.assertFalse(config["enabled"])
            self.assertEqual(config["mode"], "off")
            self.assertFalse((repo / ".lateral").exists())

            subprocess.run(
                [str(plugin / "bin" / "lateral-mode"), "mode", "strict"],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            with patch.dict(os.environ, {"LATERAL_HOME": str(data)}):
                config = load_effective_config(repo)
            self.assertTrue(config["enabled"])
            self.assertEqual(config["mode"], "strict")

    def test_reset_uses_effective_global_state_without_local_repo_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_home, tempfile.TemporaryDirectory() as tmp_repo:
            home = Path(tmp_home)
            repo = Path(tmp_repo)
            install_global(home)

            with patch.dict(os.environ, {"LATERAL_HOME": str(home)}):
                update_state_from_prompt(repo, "Sometimes checkout succeeds but payment is missing later")
                self.assertEqual(load_effective_state(repo)["runtime_mode"], "lateral_strict")

                with redirect_stdout(StringIO()):
                    main(["reset", "--path", str(repo)])

                self.assertEqual(load_effective_state(repo)["runtime_mode"], DEFAULT_STATE["runtime_mode"])

            self.assertFalse((repo / ".lateral").exists())

    def test_stop_hook_does_not_loop_when_already_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            configure_mode(root, "strict")
            update_state_from_prompt(root, "Sometimes checkout succeeds but payment is missing later")
            output = StringIO()

            with patch("sys.stdin", StringIO('{"stop_hook_active":true}')), redirect_stdout(output):
                main(["hook", "stop", "--project", str(root)])

            self.assertEqual(output.getvalue(), "")
            metrics = compute_metrics(root)
            self.assertEqual(metrics["stop_calls"], 1)
            self.assertEqual(metrics["stop_blocks"], 0)

    def test_report_command_summarizes_metrics_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_project(root)
            append_event(root, "user_prompt", {"runtime_mode": "lateral_strict", "configured_mode": "auto"})
            append_event(root, "pre_tool", {"tool": "Edit", "decision": "deny", "reason": "missing anchor"})
            append_event(root, "outcome", {"resolved": True, "rating": 5, "validation": "passed"})
            output = StringIO()

            with redirect_stdout(output):
                main(["report", "--path", str(root), "--json"])

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["workspace"], str(root.resolve()))
            self.assertEqual(payload["metrics"]["user_prompts"], 1)
            self.assertEqual(payload["metrics"]["pre_tool_denies"], 1)
            self.assertEqual(payload["assessment"], "measured")


if __name__ == "__main__":
    unittest.main()
