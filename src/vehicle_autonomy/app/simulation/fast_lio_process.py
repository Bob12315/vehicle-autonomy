"""Application launcher: owned log paths, then exec the pinned LIO process."""
import argparse,os
from pathlib import Path
from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.mid360_slam_environment import checked


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--params',required=True,type=Path)
    args,ros=parser.parse_known_args();_,binary,_=checked(resource_root(),'fast_lio')
    # LocalTools supplies a new private cwd. The external build's ROOT_DIR is ./.
    Path('Log').mkdir(mode=0o700,exist_ok=False)
    os.execv(str(binary),[str(binary),'--ros-args','--params-file',str(args.params),*ros])


if __name__=='__main__':main()
