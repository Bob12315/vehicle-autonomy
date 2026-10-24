"""Loopback Action Lab; SEND remains disabled unless explicitly granted twice."""
import argparse
from pathlib import Path
import signal

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
from vehicle_autonomy.app.bootstrap.action_driver import VehicleActionDriver
from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
from vehicle_autonomy.app.web.action_lab import ActionLab,ActionLabServer
from vehicle_autonomy.app.web.server import load_token


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulation',action='append',default=[],metavar='TARGET=MANIFEST',help='explicit live owned SITL manifest, repeat per vehicle')
    parser.add_argument('--allow-send',action='store_true',help='deployment SEND only; every writing Action additionally needs allow_send=true')
    parser.add_argument('--port',type=int,default=8770);parser.add_argument('--data-dir',type=Path,default=Path('runtime/action-lab'))
    parser.add_argument('--token-file',type=Path,required=True)
    args=parser.parse_args();drivers={};lab=server=None
    args.data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        for item in args.simulation:
            target,separator,path=item.partition('=')
            if not separator or not target or target in drivers:parser.error('unique TARGET=MANIFEST required')
            proof=OwnedActionSimulation(path);kind=proof.kind
            key='rover_phase2' if kind=='rover' and proof.manifest.get('rover_parameter_readback') else kind
            from dataclasses import replace
            profile=replace(SimulationProfile.load(resource_root()/f'simulation/profiles/{key}.toml'),port=proof.port)
            from vehicle_autonomy.vehicles.ardupilot.commands import ArduPilotCommandTranslator
            from vehicle_autonomy.vehicles.rover.ardupilot_commands import ArduRoverCommandTranslator
            from vehicle_autonomy.vehicles.plane.ardupilot_commands import ArduPlaneCommandTranslator
            translator={'rover':ArduRoverCommandTranslator,'copter':ArduPilotCommandTranslator,'plane':ArduPlaneCommandTranslator}[kind](mode_ids=profile.mode_ids)
            drivers[target]=VehicleActionDriver(target,profile,translator,proof,allow_send=args.allow_send)
        lab=ActionLab(drivers)
        server=ActionLabServer(('127.0.0.1',args.port),lab,load_token(args.token_file),args.data_dir/'audit.jsonl')
        def stop(*_):raise KeyboardInterrupt
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        print(f'Action Lab: http://127.0.0.1:{server.server_address[1]} (token is only in the private token file)',flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:
        if server:server.server_close()
        if lab:lab.close()
        else:
            for driver in drivers.values():driver.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
