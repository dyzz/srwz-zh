"""Explicit legacy-mode fixture for tests of the retained native/z protocol.

Project-default and proportional tests must use ordinary unittest.TestCase.
The production configuration is never rewritten by this fixture.
"""
import unittest
import sys
from contextlib import ExitStack
from importlib import import_module
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))


class NativeTypographyTestCase(unittest.TestCase):
    def run(self, result=None):
        policies = [import_module(name) for name in
                    ('srwz.typography_policy', 'tools.srwz.typography_policy')]
        with ExitStack() as stack:
            for policy in policies:
                stack.enter_context(patch.object(policy, 'load_policy', return_value={
                    'mode':'native','chinese_punctuation':'native'}))
                policy.candidate_enabled.cache_clear()
            try:
                return super().run(result)
            finally:
                for policy in policies:
                    policy.candidate_enabled.cache_clear()
