"""Regression controls for evidence, de-duplication and bounded process trees."""
from __future__ import annotations

import io
import json
import os
import secrets
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import ci_plan, ci_worker
from scripts import ci_process
from scripts.ci_baseline import compare_worker, load_baseline
from scripts.ci_process import registered_cleanup, run_task
from scripts.ci_fixture_registry import cleanup_scripts, register_script
from scripts.ci_results import RETIRED, collect, result_class, bootstrap_command, observed_command

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "POSIX containment is the implemented capability")
class ProcessAuditTests(unittest.TestCase):
    def invoke(self, code, timeout=2, deadline=None, log_limit=4096, executable=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        result = run_task([executable or sys.executable, "-c", code], cwd=ROOT, env=dict(os.environ),
                          directory=directory, timeout=timeout,
                          deadline=deadline or time.monotonic() + timeout, log_limit=log_limit)
        return result, directory

    def test_completed_child_is_reaped_and_logs_are_kept(self):
        result, directory = self.invoke("print('evidence')")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["cleanup"], "complete")
        self.assertEqual((directory / "stdout.txt").read_text(), "evidence\n")

    def test_exit_after_select_timeout_is_checked_by_actual_eof(self):
        with patch.object(ci_process.selectors.DefaultSelector, "select", return_value=[]):
            result, directory = self.invoke("print('completed before next readiness event')")
        self.assertEqual(result["status"], "ok")
        self.assertIn("completed before", (directory / "stdout.txt").read_text())

    def test_multiprocessing_tracker_finishes_naturally_within_bounded_drain(self):
        interpreters = [sys.executable]
        clt = Path("/Library/Developer/CommandLineTools/usr/bin/python3")
        if clt.exists() and clt.resolve() != Path(sys.executable).resolve():
            interpreters.append(str(clt))
        for executable in interpreters:
            with self.subTest(executable=executable):
                result, directory = self.invoke(
                    "import multiprocessing;q=multiprocessing.Queue();print('queue ready',flush=True)",
                    timeout=3, executable=executable)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["group_signals_sent"], [])
                self.assertEqual(result["cleanup"], "complete")
                self.assertIn("queue ready", (directory / "stdout.txt").read_text())

    def test_term_resistant_child_has_positive_control_then_kill(self):
        result, directory = self.invoke(
            "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
            "print('heartbeat',flush=True); time.sleep(60)", timeout=.9)
        self.assertIn("heartbeat", (directory / "stdout.txt").read_text())
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["cleanup"], "complete")
        self.assertLess(result["duration_s"], 1.3)

    def test_parent_exiting_does_not_hide_live_grandchild(self):
        result, directory = self.invoke(
            "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
            "\"import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "print('grandchild',flush=True);time.sleep(60)\"]);time.sleep(.15)")
        self.assertIn("grandchild", (directory / "stdout.txt").read_text())
        self.assertNotEqual(result["status"], "ok")
        self.assertEqual(result["cleanup"], "complete")

    def test_log_overflow_is_bounded_and_never_green(self):
        result, directory = self.invoke("import os,time;os.write(1,b'x'*1000000);time.sleep(60)")
        self.assertEqual(result["status"], "log_limit")
        self.assertTrue(result["logs_truncated"])
        self.assertLessEqual((directory / "stdout.txt").stat().st_size, 4096)

    def test_global_deadline_limits_a_long_task(self):
        result, _ = self.invoke("import time;time.sleep(60)", timeout=30,
                                deadline=time.monotonic() + .7)
        self.assertEqual(result["status"], "timeout")
        self.assertLess(result["duration_s"], 1.1)

    def test_registered_escapee_is_cleaned_if_worker_dies(self):
        token = secrets.token_hex(20)
        fixture = ROOT / "tests/fixtures/registered_escapee.py"
        result, directory = self.invoke(
            "import os,subprocess,sys,time;subprocess.Popen([sys.executable," + repr(str(fixture)) +
            ",os.environ['AN_KLA_CI_SPAWN_REGISTRY']," + repr(token) + "]);time.sleep(60)")
        record = json.loads((directory / "registered" / (token + ".json")).read_text())
        self.addCleanup(lambda: registered_cleanup(directory / "registered", time.monotonic() + 2))
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["cleanup"], "complete")
        with self.assertRaises(ProcessLookupError):
            os.kill(record["pid"], 0)

    def test_product_adapter_own_session_is_closed_on_worker_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = Path(temporary) / "adapter.py"
            heartbeat = Path(temporary) / "alive.json"
            adapter.write_text("import json,os,time;from pathlib import Path;Path(" + repr(str(heartbeat)) +
                               ").write_text(json.dumps({'pid':os.getpid(),'pgid':os.getpgrp()}));time.sleep(120)")
            result, directory = self.invoke(
                "from pathlib import Path;from scripts.ci_fixture_registry import register_script;"
                "from an_kla.sealed.key_adapter import SealingAdapterRunner;import sys;"
                "register_script(Path(" + repr(str(adapter)) + "));"
                "SealingAdapterRunner([sys.executable," + repr(str(adapter)) +
                "],timeout_seconds=60).wrap_cek(b'k'*32)", timeout=3)
            self.assertTrue(heartbeat.is_file(), "adapter did not start; no positive control")
            live = json.loads(heartbeat.read_text())
            self.assertEqual(live["pid"], live["pgid"])
            self.assertNotEqual(live["pgid"], result["pid"])
            self.assertEqual(result["status"], "timeout")
            self.assertEqual(result["cleanup"], "complete")
            with self.assertRaises(ProcessLookupError):
                os.kill(live["pid"], 0)

    def test_registered_group_with_dead_leader_requires_live_member_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = Path(temporary) / "parent.py"
            heartbeat = Path(temporary) / "child.json"
            token = secrets.token_hex(20)
            child = "import os,json,time;from pathlib import Path;Path(" + repr(str(heartbeat)) + ").write_text(json.dumps({'pid':os.getpid(),'pgid':os.getpgrp()}));time.sleep(120)"
            adapter.write_text("import subprocess,sys,time;subprocess.Popen([sys.executable,'-c'," + repr(child) + "," + repr(token) + "]);time.sleep(.2)")
            result, directory = self.invoke(
                "from pathlib import Path;from scripts.ci_fixture_registry import register_script;import subprocess,sys;"
                "register_script(Path(" + repr(str(adapter)) + "),member_token=" + repr(token) + ");"
                "p=subprocess.Popen([sys.executable," + repr(str(adapter)) + "],start_new_session=True);p.wait();"
                "print('leader exited',flush=True)", timeout=3)
            self.assertTrue(heartbeat.is_file(), "grandchild never started")
            self.assertIn("leader exited", (directory / "stdout.txt").read_text())
            live = json.loads(heartbeat.read_text())
            self.assertIn(result["status"], ("residual_fixture_descendants", "residual_pipes"))
            self.assertEqual(result["cleanup"], "complete")
            with self.assertRaises(ProcessLookupError):
                os.kill(live["pid"], 0)


class CaseEvidenceTests(unittest.TestCase):
    def test_observer_leaves_product_commands_untouched(self):
        for command in ([sys.executable, "-m", "an_kla", "status"],
                        [sys.executable, "private-adapter.py"], ["git", "status"]):
            self.assertIs(observed_command(command), command)

    def test_observer_preserves_startup_and_records_all_cases(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, AN_KLA_CI_OBSERVER_DIR=temporary, AN_KLA_CI_OBSERVER_RUN_ID="selftest")
            command = bootstrap_command(sys.executable, ["-m", "unittest", "tests.test_ci_local_matriz"])
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            observations = list(Path(temporary).glob("*.json"))
            self.assertEqual(len(observations), 1)
            record = json.loads(observations[0].read_text())
            self.assertTrue(record["complete"] and record["successful"])
            self.assertEqual(len(record["cases"]), 6)
            self.assertEqual(record["startup_customization"], getattr(sys.modules.get("sitecustomize"), "__file__", None))
            self.assertTrue(observations[0].with_suffix(".events.jsonl").read_text())

    def test_subtest_failure_cannot_be_hidden_by_other_success(self):
        class Sample(unittest.TestCase):
            def test_case(self):
                with self.subTest(part="critical"):
                    self.fail("injected")
        suite = unittest.TestSuite([Sample("test_case")])
        cases, _ = collect(suite)
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=result_class(unittest.TextTestResult, cases)).run(suite)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(next(iter(cases.values()))["status"], "failure")

    def test_conditional_subtest_skips_keep_one_parent_and_require_declared_scope(self):
        class Sample(unittest.TestCase):
            def test_case(self):
                for command in ("a", "b"):
                    with self.subTest(command=command):
                        self.skipTest("dependency present")
        suite = unittest.TestSuite([Sample("test_case")])
        cases, _ = collect(suite)
        key = next(iter(cases))
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=result_class(unittest.TextTestResult, cases)).run(suite)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(list(cases), [key])
        self.assertEqual(cases[key]["status"], "subtest_skip")
        report = {"complete": True, "successful": True, "cases": cases}
        policy = [{"row": "negative", "cases": [{"id": key, "when": "plain"}]}]
        rules = [{"id": key, "when": "crypto", "reason": "dependency present",
                  "subtest_suffixes": [" (command='a')", " (command='b')"]}]
        self.assertEqual(ci_plan.verify_worker(report, {"crypto": True, "export": True}, policy, rules), [])
        self.assertTrue(ci_plan.verify_worker(report, {"crypto": False, "export": True}, policy, rules))
        self.assertTrue(ci_plan.verify_worker(report, {"crypto": True, "export": True}, policy))
        class WholeSkip(unittest.TestCase):
            def test_case(self):
                self.skipTest("whole case")
        suite = unittest.TestSuite([WholeSkip("test_case")])
        whole, _ = collect(suite)
        unittest.TextTestRunner(stream=io.StringIO(), resultclass=result_class(unittest.TextTestResult, whole)).run(suite)
        self.assertEqual(next(iter(whole.values()))["status"], "skip")

    def test_class_skip_resolves_all_declared_leaf_cases(self):
        class Sample(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise unittest.SkipTest("capability absent")
            def test_one(self):
                self.fail("must not execute")
            def test_two(self):
                self.fail("must not execute")
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Sample)
        cases, _ = collect(suite)
        unittest.TextTestRunner(stream=io.StringIO(), resultclass=result_class(unittest.TextTestResult, cases)).run(suite)
        self.assertEqual(len(cases), 2)
        self.assertTrue(all(item["status"] == "skip" for item in cases.values()))

    def test_green_module_with_skipped_critical_case_is_rejected(self):
        report = {"complete": True, "successful": True, "cases": {
            "critical": {"status": "skip"}, "helper": {"status": "success"}}}
        errors = ci_plan.verify_worker(report, {"crypto": True, "export": True},
                                       [{"row": "2", "cases": [{"id": "critical", "when": "crypto"}]}])
        self.assertIn("unproved_obligation:2:critical", errors)

    def test_empty_suite_is_not_evidence(self):
        with self.assertRaisesRegex(ValueError, "empty_suite"):
            collect(unittest.TestSuite())

    @unittest.skipUnless(os.name == "posix", "POSIX containment is the implemented capability")
    def test_interruption_keeps_completed_case_events_without_false_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            observations = directory / "observations"
            observations.mkdir()
            env = dict(os.environ, AN_KLA_CI_OBSERVER_DIR=str(observations), AN_KLA_CI_OBSERVER_RUN_ID="interrupt")
            result = run_task(bootstrap_command(sys.executable, ["-m", "unittest", "tests.fixtures.ci_partial_suite"]),
                              cwd=ROOT, env=env, directory=directory / "job",
                              deadline=time.monotonic() + 1, timeout=1)
            self.assertEqual(result["status"], "timeout")
            paths = list(observations.glob("*.json"))
            self.assertEqual(len(paths), 1, "observer never started; negative control ineffective")
            self.assertFalse(json.loads(paths[0].read_text())["complete"])
            events = [json.loads(line) for line in paths[0].with_suffix(".events.jsonl").read_text().splitlines()]
            self.assertTrue(any(record["status"] == "success" for event in events
                                for record in event.get("cases", {}).values()))

    def test_retirement_cannot_silently_ignore_missing_source(self):
        with patch.object(unittest.defaultTestLoader, "discover", return_value=unittest.TestSuite([self])):
            with self.assertRaisesRegex(ValueError, "retired_orchestration_missing"):
                ci_worker.build_suite()

    def test_only_the_six_declared_orchestration_cases_are_filtered(self):
        _, cases, _ = ci_worker.build_suite()
        self.assertEqual(len(RETIRED), 6)
        self.assertFalse(RETIRED.intersection(cases))
        self.assertIn("test_sealed_matrix_rows.Row11V1BundlesUnchangedTests.test_v1_path_does_not_touch_sealed_crypto", cases)


class PlanEvidenceTests(unittest.TestCase):
    def runtime(self, prefix, crypto=False, version=None):
        return {"executable": prefix + "/python", "real_executable": "/same/binary",
                "prefix": prefix, "crypto_version": "1" if crypto else None,
                "version": version or [3, 12, 12], "crypto": crypto,
                "platform": "test", "flags": "test", "export": True}

    def test_aliases_deduplicate_but_distinct_venvs_do_not(self):
        plain = self.runtime("/plain")
        sealed = self.runtime("/sealed", True)
        normal = {"CI": None, "GITHUB_ACTIONS": None}
        cells = ci_plan.make_plan(plain, plain, sealed, [dict(plain)], normal)
        self.assertEqual(len(cells), 4)
        cells = ci_plan.make_plan(plain, plain, sealed, [self.runtime("/other")], normal)
        self.assertEqual(len(cells), 5)

    def test_primary_compatibility_python_cannot_become_principal(self):
        runtime = self.runtime("/old", version=[3, 9, 6])
        with self.assertRaisesRegex(ValueError, "principal_requires"):
            ci_plan.make_plan(runtime, runtime, runtime, [], {}, development=True)

    def test_untracked_input_changes_invalidate_signature(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ci_plan, "ROOT", Path(directory)):
            before = ci_plan.signature()
            path = Path(directory) / "untracked.md"
            path.write_text("one")
            added = ci_plan.signature()
            path.write_text("two")
            self.assertNotEqual(before, added)
            self.assertNotEqual(added, ci_plan.signature())

    def test_baseline_success_cannot_be_replaced_with_skip(self):
        common = {"real_executable": "/python", "prefix": "/venv", "version_info": [3, 12, 12],
                  "mode": {}, "sources": {}, "crypto": True, "crypto_version": "1",
                  "platform": "test", "flags": "test", "export": True}
        previous = dict(common, cases={"critical": {"status": "success"}})
        current = dict(common, cases={"critical": {"status": "skip", "detail": "hidden"}})
        self.assertIn("changed_case_outcome:critical", compare_worker(current, [previous]))

    def test_partial_green_baseline_is_not_a_transition_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = {"schema": "ankla-ci/legacy-capture-v1", "run_id": "test-run",
                        "status": "ok", "rc": 0, "cleanup": "complete",
                        "input_signature": "same", "final_signature": "same",
                        "observer_files": {"partial.json": "fake"},
                        "expected": [{"case_ids": ["one_green_helper"]}]}
            Path(directory, "legacy-run.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "legacy_inventory_does_not_match"):
                load_baseline(directory)

    def test_expired_cleanup_budget_does_not_launch_more_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "pending.json").write_text(json.dumps({"pid": 999, "token": "x" * 40}))
            with patch("scripts.ci_process.subprocess.run") as probe:
                pending = registered_cleanup(directory, time.monotonic() - 1)
            self.assertTrue(pending)
            probe.assert_not_called()

    def test_dependency_or_flag_change_is_not_runtime_equivalence(self):
        common = {"real_executable": "/python", "prefix": "/venv", "version_info": [3, 12, 12],
                  "mode": {}, "sources": {}, "crypto": True, "crypto_version": "1",
                  "platform": "test", "flags": "test", "export": True,
                  "cases": {"critical": {"status": "success"}}}
        for field in ("crypto_version", "flags"):
            changed = dict(common, **{field: "different"})
            self.assertEqual(compare_worker(changed, [common]), ["baseline_runtime_missing"])

    def test_closed_fixture_never_executes_its_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry"
            registry.mkdir()
            script = Path(temporary) / "fixture.py"
            script.write_text("from __future__ import annotations\nprint('BODY MUST NOT RUN')\n")
            with patch.dict(os.environ, {"AN_KLA_CI_SPAWN_REGISTRY": str(registry)}):
                register_script(script)
            (registry / "closed").touch()
            import subprocess
            result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=2)
            self.assertEqual(result.returncode, 99)
            self.assertEqual(result.stdout, "")

    @unittest.skipUnless(os.name == "posix", "POSIX process identity protocol")
    def test_fixture_cannot_signal_an_unverified_current_pid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "intents").mkdir()
            (root / "processes").mkdir()
            token = secrets.token_hex(20)
            script = str(root / "never-executed.py")
            (root / "intents" / (token + ".json")).write_text(json.dumps({"token": token, "script": script}))
            (root / "processes" / (token + "-fake.json")).write_text(json.dumps({
                "token": token, "script": script, "pid": os.getpid(), "pgid": os.getpgrp()}))
            with patch("scripts.ci_fixture_registry.os.kill") as signal_process:
                pending = cleanup_scripts(root, time.monotonic() + 2)
            self.assertEqual(pending, [token])
            signal_process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
