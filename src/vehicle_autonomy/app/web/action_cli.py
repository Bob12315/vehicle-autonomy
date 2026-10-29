"""Loopback Action Lab; SEND remains disabled unless explicitly granted twice."""
import argparse
import json
from pathlib import Path
import signal
from threading import Thread

from vehicle_autonomy._resources import resource_root
from vehicle_autonomy.app.bootstrap.action_ownership import OwnedActionSimulation
from vehicle_autonomy.app.bootstrap.action_driver import VehicleActionDriver
from vehicle_autonomy.app.bootstrap.simulation_profile import SimulationProfile
from vehicle_autonomy.app.web.action_lab import ActionLab,ActionLabServer
from vehicle_autonomy.app.web.server import load_token


def main(*,studio=False):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulation',action='append',default=[],metavar='TARGET=MANIFEST',help='explicit live owned SITL manifest, repeat per vehicle')
    parser.add_argument('--allow-send',action='store_true',help='deployment SEND only; every writing Action additionally needs allow_send=true')
    parser.add_argument('--port',type=int,default=8780 if studio else 8770);parser.add_argument('--data-dir',type=Path,default=Path('runtime/mission-control' if studio else 'runtime/action-lab'))
    parser.add_argument('--token-file',type=Path,required=True)
    parser.add_argument('--https-origin',help='explicit trusted HTTPS reverse-proxy origin; enables Secure browser cookies')
    parser.add_argument('--visualization-token-file',type=Path,help='independent narrow state/proposal credential; no vehicle execution permission')
    parser.add_argument('--source-time-sync',action='store_true',help='explicit owned signed SITL TIMESYNC at the existing fast owner cadence; verified UART proof required')
    parser.add_argument('--qgc-monitor-port',type=int,help='receive-only loopback UDP telemetry mirror; QGC commands are not forwarded')
    parser.add_argument('--tool-agents',type=Path,help='trusted JSON Agent ID -> private token file allowlist; enables outbound Agent channel')
    parser.add_argument('--tool-port',type=int,default=8791,help='loopback Agent channel, forward via SSH for remote hosts')
    parser.add_argument('--tool-data-dir',type=Path,help='optional private persistent Tool/Workspace state, independent of the vehicle Mission journal')
    parser.add_argument('--initialize-provider-registry',action='store_true',help='explicit one-time trusted Mission deployment bootstrap; never recovery')
    parser.add_argument('--studio-demo',action='store_true',help='register software-only Copter Mission Studio scene Actions and templates; never executes them')
    args=parser.parse_args();drivers={};lab=server=tool_service=agent_server=agent_thread=None;agent_credentials=[]
    if args.https_origin:
        from urllib.parse import urlsplit
        origin=urlsplit(args.https_origin)
        if origin.scheme!='https' or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
            parser.error('https-origin must be an HTTPS origin without credentials/path/query')
    if (args.tool_agents or args.tool_data_dir) and not studio:parser.error('Tool service requires the Mission/console entry')
    if args.studio_demo and not studio:parser.error('software Mission scenarios require the Studio entry')
    if args.visualization_token_file and not studio:parser.error('Visualization feed requires Mission/console composition')
    if args.qgc_monitor_port is not None and not 1024<=args.qgc_monitor_port<=65535:
        parser.error('QGC monitor port must be within 1024..65535')
    if args.initialize_provider_registry:
        if not studio:parser.error('provider bootstrap only belongs to the Mission deployment entry')
        from vehicle_autonomy.engine.action.provider_identity import ProviderRegistry
        ProviderRegistry.initialize()
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
            factory=None
            if args.qgc_monitor_port is not None:
                from vehicle_autonomy.vehicles.ardupilot.transports.bytes import TcpByteTransport
                from vehicle_autonomy.vehicles.ardupilot.transports.monitor import TelemetryMirror
                from vehicle_autonomy.vehicles.ardupilot.mavlink.monitor import MonitorFramer
                def factory(host,port,*,timeout_s):
                    return TelemetryMirror(TcpByteTransport.connect(host,port,timeout_s=timeout_s),args.qgc_monitor_port,frames=MonitorFramer().feed)
            drivers[target]=VehicleActionDriver(target,profile,translator,proof,allow_send=args.allow_send,transport_factory=factory,
                source_time_sync=args.source_time_sync,cycle_period_ns=20_000_000 if args.source_time_sync else None)
        if studio:
            from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
            lab=MissionControl(drivers,args.data_dir,studio_demo=args.studio_demo,simulation_allow_send=args.allow_send)
            from vehicle_autonomy.app.tools.service import ToolService
            tool_service=ToolService(args.tool_data_dir or args.data_dir/'tools');lab.tool_service=tool_service
            if args.tool_agents:
                from vehicle_autonomy.app.tools.broker import AgentServer
                from vehicle_autonomy.app.tools.schema import object_fields,identifier
                config=json.loads(args.tool_agents.read_text());object_fields(config,('schema','agents'))
                if config['schema']!=1 or type(config['agents']) is not dict:raise ValueError('Agent allowlist schema 1 required')
                credentials={}
                for agent_id,item in config['agents'].items():
                    identifier(agent_id);object_fields(item,('token_file',))
                    path=Path(item['token_file'])
                    if not path.is_absolute():raise ValueError('absolute Agent token-file path required')
                    credentials[agent_id]=load_token(path)
                if load_token(args.token_file) in credentials.values():raise ValueError('Agent credentials must differ from the browser token')
                agent_credentials=list(credentials.values())
                agent_server=AgentServer(('127.0.0.1',args.tool_port),tool_service.registry,credentials,tool_service.store.root/'agent-http.jsonl')
                agent_thread=Thread(target=agent_server.serve_forever,kwargs={'poll_interval':.2},daemon=True);agent_thread.start()
            server_class=MissionControlServer
        else:
            lab=ActionLab(drivers)
            server_class=ActionLabServer
        server=server_class(('127.0.0.1',args.port),lab,load_token(args.token_file),args.data_dir/'audit.jsonl')
        if args.visualization_token_file:
            value=load_token(args.visualization_token_file)
            if value==server.token or value in agent_credentials:raise ValueError('Visualization, operator and Agent credentials must differ')
            server.visualization_token=value
        if args.https_origin:server.browser_origin=args.https_origin;server.secure_cookies=True
        def stop(*_):raise KeyboardInterrupt
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        print(f'Action Lab: http://127.0.0.1:{server.server_address[1]} (token is only in the private token file)',flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:
        if agent_server:
            agent_server.shutdown()
            if agent_thread:agent_thread.join(4)
            agent_server.server_close()
        if server:server.server_close()
        if tool_service:tool_service.close()
        if lab:lab.close()
        else:
            for driver in drivers.values():driver.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
