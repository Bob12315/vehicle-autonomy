"""Versioned, additive SSH deployment; never changes network, kernel or old apps."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile


ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',required=True)
    parser.add_argument('--user',required=True)
    parser.add_argument('--wheelhouse',type=Path,required=True)
    parser.add_argument('--evidence-dir',type=Path,required=True)
    args=parser.parse_args()
    import paramiko
    directory=args.evidence_dir.resolve();directory.mkdir(parents=True,exist_ok=True)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    entries=subprocess.check_output(['git','ls-tree','--name-only','HEAD'],cwd=ROOT,text=True).splitlines()
    archive=directory/(commit+'.tar')
    subprocess.run(['git','archive','--format=tar','--output',str(archive),'HEAD',*[p for p in entries if p!='legacy']],cwd=ROOT,check=True)
    wheels=directory/'wheels.tar'
    with tarfile.open(wheels,'w') as stream:
        for path in sorted(args.wheelhouse.glob('*.whl')):stream.add(path,arcname=path.name)
    manifest={'source_commit':commit,'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True)),
              'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
              'wheel_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.wheelhouse.glob('*.whl'))}}
    password=os.environ.get('VAF_DEPLOY_PASSWORD') or getpass.getpass('SSH password (not stored): ')
    client=paramiko.SSHClient();client.load_system_host_keys();client.set_missing_host_key_policy(paramiko.RejectPolicy())
    transcript=[]
    try:
        client.connect(args.host,username=args.user,password=password,timeout=10,allow_agent=False,look_for_keys=False)
        def remote(command,timeout=180):
            _,out,err=client.exec_command(command,timeout=timeout)
            stdout=out.read().decode(errors='replace');stderr=err.read().decode(errors='replace')
            code=out.channel.recv_exit_status()
            transcript.append({'command':command,'exit':code,'stdout':stdout,'stderr':stderr})
            (directory/'deployment.json').write_text(json.dumps({'manifest':manifest,'operations':transcript},indent=2))
            if code:raise RuntimeError(f'remote step failed ({code}); see deployment.json')
            return stdout.strip()
        home=remote('printf %s "$HOME"')
        base=home+'/vehicle-autonomy'
        release=base+'/releases/'+commit
        q=shlex.quote
        remote('mkdir -p '+q(base+'/incoming')+' '+q(base+'/wheels')+' '+q(base+'/releases'))
        # Never overwrite an existing versioned release: an identical commit can be reused.
        sftp=client.open_sftp()
        try:
            sftp.put(str(archive),base+'/incoming/'+commit+'.tar')
            sftp.put(str(wheels),base+'/incoming/wheels.tar')
            try:sftp.stat(release);exists=True
            except FileNotFoundError:exists=False
            if exists:
                marker=json.loads(sftp.open(release+'/.source-version.json').read())
                if marker.get('archive_sha256')!=manifest['archive_sha256']:raise ValueError('existing release hash mismatch')
            else:
                remote('mkdir '+q(release)+' && tar -xf '+q(base+'/incoming/'+commit+'.tar')+' -C '+q(release))
                with sftp.open(release+'/.source-version.json','w') as stream:stream.write(json.dumps(manifest))
        finally:sftp.close()
        remote('tar -xf '+q(base+'/incoming/wheels.tar')+' -C '+q(base+'/wheels'))
        remote('test -x '+q(base+'/venv/bin/python')+' || python3 -m venv --system-site-packages '+q(base+'/venv'))
        remote(q(base+'/venv/bin/python')+' -m pip install --no-index --find-links '+q(base+'/wheels')+' -r '+q(release+'/requirements-hardware.txt'))
        remote('cd '+q(release)+' && '+q(base+'/venv/bin/python')+' -m app.hardware --check')
        remote('if test -e '+q(base+'/current')+' && ! test -L '+q(base+'/current')+'; then exit 3; fi; ln -sfn '+q(release)+' '+q(base+'/current'))
        manifest['release_path']=release
        (directory/'deployment.json').write_text(json.dumps({'manifest':manifest,'operations':transcript},indent=2))
        print(json.dumps({'deployed':True,'release':release,'started':False,'mode':'hardware_readonly'}))
    finally:client.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
