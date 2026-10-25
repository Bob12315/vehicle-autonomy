"""Read-only Phase 4 history, owned-process, port and credential cleanup audit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket

from tests.simulation.launch import ROOT, available


def run(evidence, destination):
    if destination.exists(): raise ValueError('audit evidence must be new')
    destination.mkdir(parents=True)
    baseline=json.loads((evidence/'baseline.json').read_text())
    failures=[];historical=0;fixtures=[];ports=set();epochs=[]
    for name,expected in baseline['protected'].items():
        path=ROOT/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected['sha256']:
            failures.append('historical evidence changed/missing: '+name)
        historical+=1
    for path in sorted(evidence.rglob('manifest.json')):
        if destination in path.parents:continue
        data=json.loads(path.read_text())
        if 'credential_root_identity' not in data:
            failures.append('unrecognized manifest; not adopted: '+str(path));continue
        errors=[];folder=path.parent
        if not data.get('credentials_removed') or not data.get('ports_released') or data.get('remaining_process_groups')!=[]:
            errors.append('incomplete manifest cleanup')
        for resource in data.get('owned_credential_resources',[]):
            # Only inspect explicitly registered paths; this tool never deletes.
            if (folder/resource['name']).exists():errors.append('registered credential resource remains')
        if list(folder.glob('*.private')) or list(folder.glob('sitl_state*')):
            errors.append('private state remains')
        for proc in data.get('processes',[]):
            stat=Path('/proc')/str(proc['pid'])/'stat'
            try:
                if stat.read_text().rsplit(')',1)[1].split()[19]==proc.get('start_ticks'):
                    errors.append('owned PID/start_ticks still live')
            except FileNotFoundError:pass
        values=data.get('ports',{})
        if 'tcp' in values:
            ports.update((values['tcp']+offset,socket.SOCK_STREAM) for offset in (0,2,3))
        if 'json_udp' in values:ports.add((values['json_udp'],socket.SOCK_DGRAM))
        for epoch in data.get('signing_epochs',[]):
            if 'key_sha256' in epoch:epochs.append(epoch['key_sha256'])
        fixtures.append(dict(path=str(path.relative_to(ROOT)),passed=not errors,errors=errors,
            binary_sha256=data.get('binary_sha256'),plugin_sha256=data.get('plugin_library_sha256'),
            destroyed_binary_evidence=data.get('credential_destruction',[])))
        failures.extend(str(path)+': '+e for e in errors)
    busy=[dict(port=port,type='tcp' if kind==socket.SOCK_STREAM else 'udp')
          for port,kind in sorted(ports) if not available(port,kind)]
    if busy:failures.append('owned simulation ports unavailable at final audit')
    if len(epochs)!=len(set(epochs)):failures.append('signing epoch reused across fixtures')
    # Fail on leaked credential-bearing setup messages without displaying them.
    sensitive_logs=[]
    for path in evidence.rglob('*.jsonl'):
        with path.open() as stream:
            for number,line in enumerate(stream,1):
                if ('"type": "SETUP_SIGNING"' in line or '"mavpackettype": "SETUP_SIGNING"' in line
                        or '"secret_key"' in line):
                    sensitive_logs.append(dict(path=str(path.relative_to(ROOT)),line=number));break
    if sensitive_logs:failures.append('credential-bearing log record detected; contents not displayed')
    result=dict(passed=not failures,historical_files_verified=historical,owned_fixtures=len(fixtures),
        fixtures=fixtures,ports_checked=len(ports),busy_ports=busy,signing_epochs=len(epochs),
        unique_signing_epochs=len(set(epochs)),sensitive_log_locations=sensitive_logs,failures=failures,
        read_only_audit=True)
    (destination/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence',type=Path,default=ROOT/'artifacts/phase4-mission')
    p.add_argument('--run-dir',type=Path,required=True);a=p.parse_args()
    result=run(a.evidence.resolve(),a.run_dir.resolve())
    print(json.dumps({k:result[k] for k in ('passed','historical_files_verified','owned_fixtures','ports_checked','failures')}))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
