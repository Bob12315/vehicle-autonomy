from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from tests.simulation.launch import OwnedSimulation

class OwnedProcessTests(unittest.TestCase):
    def test_transient_success_does_not_hide_long_running_or_failed_process(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'process.log';path.touch()
            for transient,code,allowed in ((True,0,True),(False,0,False),(True,1,False),(False,1,False)):
                owner=OwnedSimulation.__new__(OwnedSimulation)
                process=SimpleNamespace(poll=lambda:code,returncode=code)
                record=dict(log=str(path),name='declared-command',transient=transient)
                owner.processes=[(process,None,record)]
                if allowed:owner.assert_alive()
                else:
                    with self.assertRaises(RuntimeError):owner.assert_alive()
            record['stopping']=True
            owner.assert_alive() # Explicit stop is audited by final process-group cleanup.
