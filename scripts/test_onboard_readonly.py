"""ARM64 non-Gazebo profile: all root tests except the external Gazebo Oracle.

This is a separately declared deployment profile, not a substitute for the full
PC simulation gate. No test is marked skipped. PC-only simulator harnesses and
the Oracle remain mandatory in P26 on the simulation host.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    modules=['tests.'+path.stem for path in sorted((ROOT/'tests').glob('test_*.py'))
             if path.stem!='test_gazebo_oracle']
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in modules)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report={'passed':result.wasSuccessful() and not result.skipped,'profile':'onboard_non_gazebo',
            'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
            'modules':modules,'external_gates':{'tests.test_gazebo_oracle':'PC P26 mandatory; Gazebo bindings unavailable on board',
             'tests.simulation.*':'PC P26 mandatory; owned SITL/Gazebo/toolchain checkouts are PC-only'},
            'physical_vehicle_io':'none; actual serial source configuration remains null'}
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
