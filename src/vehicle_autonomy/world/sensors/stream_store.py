"""Owned fixed-slot payload storage; old references fail by content digest.

The directory is created fresh for one worker epoch. No caller-selected path is
opened by load(), and only fixed names in this private directory are replaced.
"""
import hashlib
import os
import stat
from pathlib import Path
from threading import Lock
from vehicle_autonomy.contracts.streams import DataReference


class StreamReader:
    def __init__(self,directory,*,slots=8,max_bytes=8*1024*1024):
        if type(slots) is not int or not 2<=slots<=32 or type(max_bytes) is not int or not 1<=max_bytes<=8*1024*1024:
            raise ValueError('bounded stream storage required')
        self.root=Path(directory).absolute()
        if self.root.resolve()!=self.root:raise ValueError('real stream directory required')
        info=self.root.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('private owned stream directory required')
        self.identity=(info.st_dev,info.st_ino);self.slots=slots;self.max_bytes=max_bytes
    def load(self,reference):
        if not isinstance(reference,DataReference) or reference.reference_id not in {f'slot-{i}' for i in range(self.slots)}:
            raise ValueError('reference is not an owned fixed slot')
        if self.root.resolve()!=self.root:raise ValueError('stream directory changed')
        directory_fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            info=os.fstat(directory_fd)
            if (info.st_dev,info.st_ino)!=self.identity:raise ValueError('stream directory identity changed')
            fd=os.open(reference.reference_id,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory_fd)
        finally:os.close(directory_fd)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_size!=reference.byte_size or info.st_size>self.max_bytes:
                raise ValueError('stream payload identity/size changed')
            chunks=[];total=0
            while chunk:=os.read(fd,min(65536,self.max_bytes+1-total)):
                chunks.append(chunk);total+=len(chunk)
                if total>self.max_bytes:raise ValueError('payload grew beyond budget')
            data=b''.join(chunks)
        finally:os.close(fd)
        if hashlib.sha256(data).hexdigest()!=reference.sha256:raise ValueError('stream reference overwritten or corrupt')
        return data


class StreamStore(StreamReader):
    def __init__(self,directory,*,slots=8,max_bytes=8*1024*1024):
        if type(slots) is not int or not 2<=slots<=32 or type(max_bytes) is not int or not 1<=max_bytes<=8*1024*1024:
            raise ValueError("bounded stream storage required")
        root=Path(directory).absolute()
        if root.resolve()!=root:raise ValueError('real stream directory required')
        root.mkdir(mode=0o700,parents=True,exist_ok=False)
        super().__init__(root,slots=slots,max_bytes=max_bytes)
        self._next={};self._lock=Lock()
    def put(self,payload,media_type,dimensions=(),*,channel="default"):
        if type(payload) is not bytes or len(payload)>self.max_bytes:raise ValueError('payload outside byte budget')
        digest=hashlib.sha256(payload).hexdigest()
        with self._lock:
            if channel not in self._next:
                if len(self._next)>=self.slots//2:raise ValueError('channel capacity exhausted')
                self._next[channel]=[len(self._next)*2,0]
            base,count=self._next[channel];slot=base+count%2;self._next[channel][1]+=1
            destination=self.root/f'slot-{slot}'
            temporary=self.root/f'.slot-{slot}.tmp'
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                view=memoryview(payload)
                while view:
                    n=os.write(fd,view)
                    if n<=0:raise OSError('stream payload short write')
                    view=view[n:]
            finally:os.close(fd)
            os.replace(temporary,destination)
            return DataReference(f'slot-{slot}',digest,len(payload),media_type,dimensions)
