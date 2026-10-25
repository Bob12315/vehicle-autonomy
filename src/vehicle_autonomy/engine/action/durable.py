"""Small checksummed records, committed before a side effect/evidence escapes.

Trusts the local OS owner and a filesystem honoring file/directory fsync and
atomic rename. Missing/corrupt established state is never initialized by read.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
from uuid import uuid4


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def durable_directories(path):
    """Commit new parent directory entries before committing records in them."""
    path=Path(path).absolute()
    if path.resolve()!=path:raise ValueError('real state path required')
    missing=[];current=path
    while not current.exists():missing.append(current);current=current.parent
    for directory in reversed(missing):
        try:directory.mkdir(mode=0o700)
        except FileExistsError:pass
        fd=os.open(directory.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)


class DurableRecord:
    def __init__(self,path,*,limit=4*1024*1024):
        self.path=Path(path).absolute();self.limit=limit;self.failed=False
        if self.path.resolve()!=self.path:raise ValueError('real durable record path required')
        info=self.path.parent.stat()
        if info.st_uid!=os.getuid() or not stat.S_ISDIR(info.st_mode):raise ValueError('owned state directory required')

    def read(self):
        if self.failed:raise OSError('durable state unavailable after persistence failure')
        fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
                    or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>self.limit):
                raise ValueError('invalid durable state ownership or size')
            with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(self.limit+1)
            wrapper=json.loads(raw)
            if (type(wrapper) is not dict or set(wrapper)!={'version','payload','sha256'}
                    or type(wrapper['version']) is not int or wrapper['version']!=1
                    or type(wrapper['sha256']) is not str
                    or hashlib.sha256(canonical(wrapper['payload'])).hexdigest()!=wrapper['sha256']
                    or raw!=canonical(wrapper)+b'\n'):
                raise ValueError('durable state checksum or format invalid')
            return wrapper['payload']
        finally:os.close(fd)

    def write(self,payload,*,create=False):
        if self.failed:raise OSError('durable state unavailable after persistence failure')
        raw=canonical({'version':1,'payload':payload,'sha256':hashlib.sha256(canonical(payload)).hexdigest()})+b'\n'
        if len(raw)>self.limit:raise ValueError('durable state budget exhausted')
        temp=self.path.with_name('.'+self.path.name+'.pending-'+uuid4().hex)
        fd=None;directory=None
        try:
            if not create:self.read()  # Deletion/corruption cannot reset an established epoch.
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            if os.write(fd,raw)!=len(raw):raise OSError('durable record partial write')
            os.fsync(fd);os.close(fd);fd=None
            directory=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            if create:
                # link is atomic no-replace; initialization never overwrites.
                os.link(temp,self.path,follow_symlinks=False);os.unlink(temp)
            else:os.replace(temp,self.path)
            os.fsync(directory)
        except BaseException:
            self.failed=True
            raise
        finally:
            if fd is not None:os.close(fd)
            if directory is not None:os.close(directory)
            try:temp.unlink()
            except FileNotFoundError:pass
