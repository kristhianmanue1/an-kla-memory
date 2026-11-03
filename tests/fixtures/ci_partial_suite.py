"""Explicit observer failure-control fixture; excluded from normal discovery."""
import time
import unittest


class PartialEvidence(unittest.TestCase):
    def test_1_completed(self):
        self.assertTrue(True)

    def test_2_interrupted(self):
        time.sleep(120)
