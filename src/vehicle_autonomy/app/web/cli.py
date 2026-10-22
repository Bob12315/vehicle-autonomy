"""Web composition calls the existing Application Unix API; owns no hardware."""
import argparse
from pathlib import Path
import signal

from vehicle_autonomy.app.api.control import request, socket_path
from vehicle_autonomy.app.operator.service import OperatorService
from vehicle_autonomy.app.web.server import ConsoleServer, load_token


class ApplicationClient:
    def __init__(self,path):
        self.path=path
    def handle(self,operation,payload):
        response=request(self.path,operation,payload)
        if not response['ok']:
            raise ValueError(response['error'])
        return response['result']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-socket')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data-dir',default='artifacts/hardware-ready/console')
    parser.add_argument('--token-file',required=True)
    parser.add_argument('--llm-config')
    parser.add_argument('--missions',default='')
    args=parser.parse_args()
    directory=Path(args.data_dir);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    from vehicle_autonomy.autonomy.intelligence.proposals import LlmAdapter
    service=OperatorService(ApplicationClient(args.control_socket or socket_path('hardware_readonly')),directory,
        llm=LlmAdapter.load(args.llm_config) if args.llm_config else None,
        missions=tuple(filter(None,args.missions.split(','))))
    server=ConsoleServer(('127.0.0.1',args.port),service,load_token(args.token_file),directory/'audit.jsonl')
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
