"""P21 actual named-goal Application/Nav2/Rover acceptance."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from tests.simulation.launch import ROOT,install_signal_cleanup
from tests.simulation.path_following import run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-send',action='store_true')
    parser.add_argument('--case',choices=('tracking','cancel','map_loss','plan_change','timeout','planning_cancel','unreachable','replan','blocked','replan_cancel','map_goal','business_inspect','business_cancel','business_loss'),default='tracking')
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--room-yaw',type=float,choices=(0.,.15))
    parser.add_argument('--boundary-library',type=Path)
    args=parser.parse_args()
    if not args.allow_send:parser.error('explicit simulation SEND required')
    install_signal_cleanup()
    directory=(args.run_dir or ROOT/'artifacts/simulation'/f'goal-{args.case}-{uuid4().hex[:8]}').resolve()
    if args.boundary_library:
        import os
        os.environ['VAF_SLAM_BOUNDARY_LIBRARY']=str(args.boundary_library.resolve())
    report=run(directory,args.case,autonomous=True,room_yaw=args.room_yaw)
    print(json.dumps({'directory':str(directory),**report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
