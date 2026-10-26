"""Owned SIMULATION-only telemetry provisioning before any application owner.

The current AP dynamically creates MAV1 parameters after initial defaults load.
Set and independently read back only intended telemetry rates, never actuator,
fence, arming, physical or safety parameters. No second application writer.
"""
from pathlib import Path
import socket
import time


def telemetry_rates(owned,*,hz=10):
    from pymavlink.dialects.v20 import ardupilotmega as mav
    if owned.kind!='rover' or (owned.run_dir/'action-owner.lock').exists():raise ValueError('fresh unowned Rover simulation provisioning only')
    if hz not in (10,20):raise ValueError('explicit qualified telemetry rate required')
    rates={'MAV1_POSITION':float(hz),'MAV1_EXTRA1':float(hz),'MAV1_EXT_STAT':5.}
    parser=mav.MAVLink(None);parser.robust_parsing=True;peer=mav.MAVLink(None,srcSystem=250,srcComponent=191)
    sent=False;observed={name:[] for name in ("ATTITUDE","LOCAL_POSITION_NED","GLOBAL_POSITION_INT")};ready=False
    with socket.create_connection(('127.0.0.1',owned.port),timeout=1) as connection:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            owned.assert_alive()
            try:raw=connection.recv(8192)
            except socket.timeout:continue
            for message in parser.parse_buffer(raw) or []:
                if message.get_type()=='BAD_DATA' or owned.receive_signing.verify(message,system=1,component=1) is None:continue
                if message.get_type()=='HEARTBEAT' and not sent:
                    if message.base_mode&128:raise ValueError('unarmed owned SITL required for telemetry setup')
                    for name,value in rates.items():
                        connection.sendall(peer.param_set_encode(1,1,name.encode(),value,mav.MAV_PARAM_TYPE_INT16).pack(peer));peer.seq=(peer.seq+1)&255
                    # AP initializes message scheduling before dynamic stream
                    # defaults load; PARAM_VALUE alone does not prove frequency.
                    for msgid in (30,32,33):
                        connection.sendall(peer.command_long_encode(1,1,mav.MAV_CMD_SET_MESSAGE_INTERVAL,0,msgid,1_000_000//hz,0,0,0,0,0).pack(peer));peer.seq=(peer.seq+1)&255
                    sent=True
                name=message.get_type()
                if sent and name in observed:
                    observed[name].append(int(message.time_boot_ms));observed[name]=observed[name][-3:]
            if sent and all(len(v)==3 and all(0<b-a<=200 for a,b in zip(v,v[1:])) for v in observed.values()):
                ready=True;break
    if not sent:raise TimeoutError('no authenticated unarmed provisioning state')
    if not ready:raise TimeoutError('actual AP source message frequency did not reach the explicit rate')
    owned.manifest['phase5_interval_probe']={name:[b-a for a,b in zip(v,v[1:])] for name,v in observed.items()}
    owned.verify_parameters(rates,'phase5_telemetry_rates')
