"""Actual installed software only; unavailable/WAITING is never reported PASS."""
import argparse
import json
from pathlib import Path
import time

from vehicle_autonomy.app.tools.local import LocalTools
from vehicle_autonomy.app.tools.storage import Store
from .helpers import CTX, wait


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry',type=Path,required=True);p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--tool',action='append',default=[]);p.add_argument('--observe-s',type=float,default=12)
    a=p.parse_args();a.run_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
    store=Store(a.run_dir/'state');local=LocalTools(json.loads(a.registry.read_text())['tools'],store)
    report=dict(source='actual locally installed executables, no mocks',tools=[])
    try:
        for entry in local.snapshot():
            tool=entry['manifest']['id']
            if a.tool and tool not in a.tool:continue
            profile=next(iter(entry['manifest']['profiles']))
            item=dict(id=tool,profile=profile,check=entry['checks'][profile]);report['tools'].append(item)
            try:
                local.execute('launch',tool,profile,CTX)
                end=time.monotonic()+a.observe_s
                while time.monotonic()<end:
                    view=local._view(local.instances[tool])
                    if view['ready'] or view['state'] in ('FAILED','UNKNOWN'):break
                    time.sleep(.1)
                item['observed']=local._view(local.instances[tool]);item['ready_pass']=item['observed']['ready']
                local.execute('stop',tool,profile,CTX)
                wait(lambda:local.instances[tool]['process'].poll() is not None,15)
                item['exit']=local._view(local.instances[tool])
            except Exception as exc:item.update(error=type(exc).__name__+': '+str(exc),ready_pass=False)
            (a.run_dir/'summary.json').write_text(json.dumps(report,indent=2))
    finally:
        local.close();store.close();(a.run_dir/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps([dict(id=t['id'],ready_pass=t['ready_pass'],error=t.get('error'),state=t.get('observed',{}).get('state')) for t in report['tools']],indent=2))


if __name__=='__main__':main()
