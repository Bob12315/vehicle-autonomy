"""Read-only admission proof for an explicitly launched, owned local SITL.

This is an OS-owner trust boundary, not protection from the same OS user's
malicious processes. It never provisions signing, reads EEPROM or kills tasks.
"""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import stat

from vehicle_autonomy.vehicles.ardupilot.mavlink.signing import ReceiveSigning


class _DurableSigning(ReceiveSigning):
    def __init__(self,key,*,initial_timestamp,persist,reserve_steps=128):
        super().__init__(key,initial_timestamp=initial_timestamp);self._persist=persist
        if type(reserve_steps) is not int or not 0<=reserve_steps<=128:raise ValueError('bounded durable timestamp reservation required')
        self._reserved=initial_timestamp;self._reserve_steps=reserve_steps
    def verify(self,message,*,system,component):
        timestamp=super().verify(message,system=system,component=component)
        # Persist BEFORE authenticated data can enter Session/World. Corrupt
        # state after an interrupted update fails closed on the next startup.
        if timestamp is not None and timestamp>self._reserved:
            reserved=min(2**48-1,timestamp+self._reserve_steps)
            self._persist(reserved);self._reserved=reserved
        return timestamp


class OwnedActionSimulation:
    def __init__(self,manifest_path):
        self.path=Path(manifest_path).absolute()
        if self.path.resolve()!=self.path or self.path.name!='manifest.json':raise ValueError('explicit real manifest required')
        self.root=self.path.parent
        info=self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('simulation evidence must be owned')
        self.identity=(info.st_dev,info.st_ino)
        self.manifest=json.loads(self.path.read_text())
        m=self.manifest
        if m.get('ended_at') or m.get('credentials_removed') or m.get('kind') not in ('rover','copter','plane'):
            raise ValueError('live owned simulation required')
        if m.get('credential_root_identity')!={'device':info.st_dev,'inode':info.st_ino}:raise ValueError('ownership registry mismatch')
        self.kind=m['kind'];self.port=m['ports']['tcp'];self.world=m['world'];self.model=m['model']
        if self.port!=5760+10*m['instance']:raise ValueError('isolated SITL instance required')
        self.processes=[p for p in m['processes'] if p['exit_code'] is None]
        if {p['name'] for p in self.processes}!={'sitl','gazebo'}:raise ValueError('one live simulation epoch required')
        binary=Path(m['binary_path']).resolve()
        if binary.name!={'rover':'ardurover','copter':'arducopter','plane':'arduplane'}[self.kind]:raise ValueError('binary kind mismatch')
        if hashlib.sha256(binary.read_bytes()).hexdigest()!=m['binary_sha256']:raise ValueError('binary provenance changed')
        self.assert_alive()
        private=self.root/'receive-signing.private';pi=private.lstat()
        record=next((r for r in m['owned_credential_resources'] if r['name']==private.name and r['kind']=='file'),None)
        if (record is None or (pi.st_dev,pi.st_ino)!=(record['device'],record['inode']) or pi.st_uid!=os.getuid()
                or not stat.S_ISREG(pi.st_mode) or pi.st_nlink!=1 or stat.S_IMODE(pi.st_mode)!=0o600):
            raise ValueError('owned private provisioning interface required')
        # Provisioning contract only. Its contents must never enter events,
        # exceptions, metadata, repr, reports, HTTP responses, or Git.
        with private.open() as stream:configuration=json.load(stream)
        self._lockfd=None;self._floorfd=None
        try:
            self._lockfd=self._owned_file('action-owner.lock')[0]
            fcntl.flock(self._lockfd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self._floorfd,created=self._owned_file('action-receive-floor')
            initial=configuration['floor']
            if created:self._persist(initial)
            else:
                raw=os.read(self._floorfd,65)
                if not raw.isdigit() or len(raw)>20:raise ValueError('receive watermark unavailable; create a fresh fixture')
                initial=max(initial,int(raw))
            self.receive_signing=_DurableSigning(bytes.fromhex(configuration['key']),initial_timestamp=initial,persist=self._persist)
        except Exception:
            self.close();raise ValueError('owned signing epoch unavailable, already in use, or corrupt') from None

    def _owned_file(self,name):
        path=self.root/name;created=False
        try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600);created=True
        except FileExistsError:fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:
            os.close(fd);raise ValueError('private owned epoch file required')
        return fd,created

    def _persist(self,timestamp):
        os.lseek(self._floorfd,0,os.SEEK_SET);os.ftruncate(self._floorfd,0)
        raw=str(timestamp).encode('ascii')
        if os.write(self._floorfd,raw)!=len(raw):raise OSError('receive watermark partial write')
        os.fsync(self._floorfd)

    def close(self):
        for name in ('_floorfd','_lockfd'):
            fd=getattr(self,name,None)
            if fd is not None:os.close(fd);setattr(self,name,None)

    def assert_alive(self):
        info=self.root.lstat()
        if (info.st_dev,info.st_ino)!=self.identity or self.root.resolve()!=self.root:raise RuntimeError('owned simulation root changed')
        for p in self.processes:
            proc=Path('/proc')/str(p['pid'])
            fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
            if fields[0]=='Z' or fields[19]!=str(p['start_ticks']) or os.getpgid(p['pid'])!=p['pgid']:
                raise RuntimeError('owned simulation epoch ended')
            command=(proc/'cmdline').read_bytes().split(b'\0')[:-1]
            expected=[os.fsencode(arg) for arg in p['command']]
            # gz's launcher execs the distro Ruby interpreter. Require its
            # exact original CLI suffix and owned world, not argv[0] equality.
            valid=(command==expected if p['name']=='sitl' else
                   (command and command[0]==b' '.join(expected) and all(not arg for arg in command[1:])) or
                   (len(command)>=len(expected) and command[-len(expected)+1:]==expected[1:]
                    and any(Path(os.fsdecode(arg)).name=='gz' for arg in command[:2])))
            if not valid:raise RuntimeError('owned process command changed: '+p['name'])
            if (proc/'cwd').resolve()!=Path(p['cwd']).resolve():raise RuntimeError('owned process cwd changed')
            if p['name']=='sitl':
                state=Path(p['cwd'])
                record=next((r for r in self.manifest['owned_credential_resources'] if r['name']==state.name and r['kind']=='directory'),None)
                si=state.lstat()
                if state.parent!=self.root or record is None or (si.st_dev,si.st_ino)!=(record['device'],record['inode']):
                    raise RuntimeError('SITL is not in its registered temporary state')
