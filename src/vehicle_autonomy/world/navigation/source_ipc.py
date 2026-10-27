"""Bounded same-host source frames from the public rclcpp MessageInfo adapter."""
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import struct
import time

WIRE=struct.Struct('<8sBBHQQ6d24s64s')

@dataclass(frozen=True,slots=True)
class NativeSourceFrame:
    channel:int
    source_ns:int
    received_ns:int
    values:tuple
    gid:bytes
    frame_id:str

class NativeSourceSocket:
    def __init__(self,name,pid,start_ticks):
        if not isinstance(name,str) or not name.startswith('@vaf-native-') or len(name)>100:raise ValueError('explicit private native source socket required')
        if type(pid) is not int or pid<=0 or not isinstance(start_ticks,str) or not start_ticks.isdigit():raise ValueError('actual source process identity required')
        self.pid=pid;self.start_ticks=start_ticks;self.rejected=0;self.accepted=0
        self.socket=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM|socket.SOCK_NONBLOCK)
        self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1);self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,65536)
        self.socket.bind('\0'+name[1:])
    def drain(self):
        frames=[]
        for _ in range(32):
            try:data,ancillary,flags,_=self.socket.recvmsg(WIRE.size+1,socket.CMSG_SPACE(struct.calcsize('3i')))
            except BlockingIOError:break
            try:
                credentials=[struct.unpack('3i',v) for level,kind,v in ancillary if level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS]
                if flags or len(data)!=WIRE.size or len(credentials)!=1 or credentials[0][:2]!=(self.pid,os.getuid()):raise ValueError('native IPC sender/size mismatch')
                fields=Path(f'/proc/{self.pid}/stat').read_text().rsplit(')',1)[1].split()
                if fields[19]!=self.start_ticks or fields[0]=='Z':raise ValueError('native source process epoch changed')
                magic,channel,gid_size,reserved,source,received,*rest=WIRE.unpack(data);values=tuple(rest[:6]);gid,frame=rest[6:]
                if magic!=b'VAFNV01\0' or reserved or channel not in (0,1) or gid_size not in (16,24) or not source or not 0<received<=time.monotonic_ns():raise ValueError('native source frame format/time')
                gid=gid[:gid_size]
                if not any(gid):raise ValueError('missing actual publisher GID')
                frame=frame.split(b'\0',1)[0].decode('ascii')
                frames.append(NativeSourceFrame(channel,source,received,values,gid,frame));self.accepted+=1
            except (ValueError,OSError,UnicodeError,struct.error):self.rejected+=1
        return frames
    def close(self):self.socket.close()
