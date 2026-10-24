"""Launch only a fresh owned fixture for manual Action Lab use; no control."""
import argparse
from pathlib import Path
import signal
import time
from tests.simulation.launch import OwnedSimulation,install_signal_cleanup


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kind',choices=['rover','copter','plane'],required=True)
    p.add_argument('--run-dir',type=Path,required=True);args=p.parse_args()
    install_signal_cleanup();root=args.run_dir.resolve();root.mkdir(parents=True,exist_ok=False)
    fixture=OwnedSimulation(root,args.kind,confirmation_signing=True,rover_native_rtl=args.kind=='rover')
    try:
        fixture.start();print('Owned read-only fixture manifest: '+str(root/'manifest.json'),flush=True)
        while True:fixture.assert_alive();time.sleep(.2)
    except KeyboardInterrupt:pass
    finally:fixture.close()


if __name__=='__main__':main()
