"""A compaction probe distinguishes retryable races from terminal errors."""
from __future__ import annotations

import subprocess
import unittest
from unittest.mock import Mock, patch

from an_kla.store import LockBusyError
from an_kla.write_policy import WritePolicyError
from benchmarks.scale.scenarios_durability import _probe_writer, _probe_and_collect


class CompactionProbeRetryTests(unittest.TestCase):
    def store(self):
        store = Mock()
        store.read_current.return_value = "sha256:" + "a" * 64
        store.plan_write.return_value = {"decision": {}, "plan": {}}
        store.commit_write_plan.return_value = {"committed": True}
        return store

    def test_retries_plan_and_commit_contention_and_cas(self):
        store = self.store()
        plan = {"decision": {}, "plan": {}}
        store.plan_write.side_effect = [
            LockBusyError("writer_gate_busy"),
            WritePolicyError("write_plan_base_changed"), plan, plan, plan,
        ]
        store.commit_write_plan.side_effect = [
            WritePolicyError("write_plan_base_changed"),
            LockBusyError("write_lock_busy"), {"committed": True},
        ]
        result = _probe_writer(store, ["subject"], 10)
        self.assertTrue(result["committed"])
        self.assertEqual(result["cas_retries"], 2)
        self.assertEqual(result["lock_busy_errors"], 2)
        self.assertEqual(store.commit_write_plan.call_count, 3)

    def test_terminal_policy_errors_are_not_reported_as_cas(self):
        for phase in ("plan_write", "commit_write_plan"):
            with self.subTest(phase=phase):
                store = self.store()
                getattr(store, phase).side_effect = WritePolicyError("invalid_write_plan")
                with self.assertRaises(WritePolicyError) as caught:
                    _probe_writer(store, ["subject"], 10)
                self.assertEqual(caught.exception.code, "invalid_write_plan")


class CompactionProbeCleanupTests(unittest.TestCase):
    def test_failed_probe_reaps_child_even_if_termination_times_out(self):
        for times_out in (False, True):
            with self.subTest(times_out=times_out):
                proc = Mock()
                proc.poll.return_value = None
                proc.communicate.side_effect = (
                    [subprocess.TimeoutExpired("compact", 10), ("", "")]
                    if times_out else [("", "")]
                )
                failure = WritePolicyError("invalid_write_plan")
                with patch("benchmarks.scale.scenarios_durability._probe_writer",
                           side_effect=failure):
                    with self.assertRaises(WritePolicyError) as caught:
                        _probe_and_collect(proc, Mock(), ["subject"], 0, 1, 1)
                self.assertIs(caught.exception, failure)
                proc.terminate.assert_called_once()
                self.assertEqual(proc.kill.call_count, int(times_out))
                self.assertEqual(proc.communicate.call_count, 1 + int(times_out))

    def test_collection_timeout_after_successful_probe_reaps_child(self):
        proc = Mock()
        proc.poll.return_value = None
        timeout = subprocess.TimeoutExpired("compact", 1)
        proc.communicate.side_effect = [timeout, ("", "")]
        with patch("benchmarks.scale.scenarios_durability._probe_writer",
                   return_value={"committed": True}):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                _probe_and_collect(proc, Mock(), ["subject"], 0, 1, 1)
        self.assertIs(caught.exception, timeout)
        proc.terminate.assert_called_once()
        proc.kill.assert_not_called()
        self.assertEqual(proc.communicate.call_count, 2)

    def test_unconfirmed_outcome_is_not_retried_as_cas(self):
        store = CompactionProbeRetryTests().store()
        store.commit_write_plan.return_value = {"committed": None}
        with self.assertRaisesRegex(RuntimeError, "probe_commit_not_confirmed"):
            _probe_writer(store, ["subject"], 10)
        store.commit_write_plan.assert_called_once()
