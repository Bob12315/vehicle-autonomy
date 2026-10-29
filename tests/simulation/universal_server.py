"""Dedicated native web server for browser acceptance, separate from Playwright.

Production browser clients do not share the vehicle owner's Python interpreter.
The test preserves that process boundary instead of importing the UI client's
large object graph into the real-time application.
"""
import argparse
import json
from pathlib import Path
import signal
from threading import Thread

from vehicle_autonomy.app.web.mission_control import MissionControl,MissionControlServer
from vehicle_autonomy.app.web.server import load_token


def serve(directory,allow_send=False):
    directory=Path(directory).resolve()
    token=load_token(directory/'web-token.private')
    app=MissionControl({},directory/'application',simulation_allow_send=allow_send)
    server=MissionControlServer(('127.0.0.1',0),app,token,directory/'http-audit.jsonl')
    stopping=False
    def stop(*_):
        nonlocal stopping
        if not stopping:
            stopping=True
            Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    (directory/'server-ready.json').write_text(json.dumps({'port':server.server_address[1]}))
    try:server.serve_forever(poll_interval=.1)
    finally:
        server.server_close();app.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--allow-send',action='store_true');a=p.parse_args();serve(a.directory,a.allow_send)
