"""HTTP terminal evidence must belong to the admitted provider epoch and job."""
from pathlib import Path
import tempfile
import unittest

from tests.simulation.http_job_identity import CASES,run_case


class HttpJobIdentityTests(unittest.TestCase):
    def exercise(self,case):
        with tempfile.TemporaryDirectory() as directory:
            result=run_case(Path(directory)/case,case)
            self.assertTrue(result['passed'])
            self.assertTrue(result['server_threads_stopped'])


for case in CASES:
    def test(self,name=case):self.exercise(name)
    setattr(HttpJobIdentityTests,'test_'+case,test)
