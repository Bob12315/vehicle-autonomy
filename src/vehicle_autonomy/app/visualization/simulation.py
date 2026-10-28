"""Observe an already Framework-owned simulation; never launch/kill its PIDs.

Vehicle admission and simulator lifecycle stay with the existing trusted
launcher. Workspace stops only this observer, not the vehicle or another tool.
"""
import argparse,hashlib,json,os,signal,time
from pathlib import Path
from urllib.parse import urlencode
from .config import load,vehicle_context
from .source import Client


def identity(manifest):
    fields=dict(kind=manifest.get('kind'),processes=[{k:p.get(k) for k in ('name','pid','pgid','start_ticks')} for p in manifest.get('processes',[]) if p.get('name') in ('gazebo','sitl')])
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()


def inspect(path,component,kind):
    path=Path(path)
    if not path.is_absolute() or path.is_symlink() or path.stat().st_uid!=os.getuid() or path.stat().st_size>65536:raise ValueError('owned public simulation manifest required')
    manifest=json.loads(path.read_text())
    if not manifest.get('ready') or manifest.get('kind')!=kind or manifest.get('framework_runtime') is not True:raise ValueError('matching active Framework simulation required')
    process=next(p for p in manifest['processes'] if p['name']==component)
    pid=process['pid'];proc=Path('/proc')/str(pid)
    if proc.stat().st_uid!=os.getuid() or os.getpgid(pid)!=process['pgid']:raise ValueError('simulation process owner/group changed')
    fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
    if fields[0]=='Z' or fields[19]!=process['start_ticks']:raise ValueError('simulation process epoch changed')
    return identity(manifest)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('watch','probe'));p.add_argument('--component',choices=('gazebo','sitl'),required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    cfg=load(a.config);ctx=vehicle_context();client=Client(cfg,ctx['vehicle_id']);stop=False
    def stopping(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,stopping);signal.signal(signal.SIGINT,stopping)
    while not stop:
        try:
            expected=inspect(a.manifest,a.component,ctx['vehicle_type']);source=client.request('/api/visualization/state?'+urlencode(dict(target=ctx['vehicle_id'])))
            ready=source['simulation_id']==expected and source['environment']=='simulation' and source['valid']
            reason=None if ready else 'Framework source does not match the live owned simulator or data is stale'
        except (OSError,ValueError,KeyError,StopIteration):ready=False;reason='owned simulation or Framework feed unavailable'
        print(json.dumps(dict(status='READY' if ready else 'WAITING',component=a.component,observed_only=True,reason=reason)),flush=True)
        if a.operation=='probe':return 0 if ready else 2
        for _ in range(10):
            if stop:break
            time.sleep(.1)
    return 0


if __name__=='__main__':raise SystemExit(main())
