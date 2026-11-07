"""Read-only post-run audit of real MID-360 acceptance ownership and ports."""
import argparse,json,os,socket
from collections import Counter
from pathlib import Path

from .mid360 import remaining_owned


def audit(directory):
    directory=Path(directory).resolve();native=directory/'native/application/simulation'
    source=json.loads((directory/'result.json').read_text())
    result=dict(status='FAIL',processes=[],tools={},ports=[],remaining=[])
    try:
        for manifest in native.glob('sim-*/**/session.json'):
            saved=json.loads(manifest.read_text())
            for process in saved['processes']:
                pid=process['pid'];same=False
                try:
                    fields=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
                    same=fields[19]==process['start_ticks']
                except FileNotFoundError:pass
                result['processes'].append(dict(pid=pid,name=process['name'],original_start_ticks=process['start_ticks'],still_present=same))
                assert not same,process
        for log in native.glob('sim-*/vehicle-*/mid360/tools/*/audit.jsonl'):
            launched=Counter();exited=Counter()
            for line in log.read_text().splitlines():
                event=json.loads(line)
                if event['operation']=='tool.running':launched[event['tool']]+=1
                if event['operation']=='tool.exit':
                    exited[event['tool']]+=1;assert event['cleanup_confirmed'],event
            assert launched==exited,(str(log),launched,exited)
            result['tools'][str(log.relative_to(directory))]=dict(launched=dict(launched),cleaned=dict(exited))
        checked=set()
        for report in native.glob('sim-*/report.json'):
            saved=json.loads(report.read_text());assert saved['cleanup']=='COMPLETE',str(report)
            for vehicle in saved['vehicles']:
                # Vehicle lease records include FDM, UDP and TCP auxiliary
                # ports. Session.manifest['ports'] alone lists only primary TCP.
                for kind,values in vehicle['ports'].items():
                    for port in values if isinstance(values,list) else [values]:
                        protocol='tcp' if kind.startswith('tcp') else 'udp'
                        if (protocol,port) in checked:continue
                        with socket.socket(socket.AF_INET,socket.SOCK_STREAM if protocol=='tcp' else socket.SOCK_DGRAM) as probe:
                            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);probe.bind(('127.0.0.1',port))
                        checked.add((protocol,port));result['ports'].append(dict(kind=kind,protocol=protocol,port=port,released=True))
        assert {'tcp','tcp_aux','fdm','udp'} <= {p['kind'] for p in result['ports']},result['ports']
        result['remaining']=remaining_owned(directory,source['runtime']['partition'])
        assert not result['remaining'],result['remaining']
        result['status']='PASS'
    except Exception as exc:result['error']=type(exc).__name__+': '+str(exc)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True,type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=audit(args.run_dir);output=args.output or args.run_dir/'post-cleanup-audit.json'
    with output.open('x') as handle:json.dump(result,handle,indent=2);handle.write('\n')
    print(json.dumps(dict(status=result['status'],processes=len(result['processes']),ports=len(result['ports']),error=result.get('error'))))
    raise SystemExit(0 if result['status']=='PASS' else 1)
