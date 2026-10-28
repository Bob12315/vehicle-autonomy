"""Bounded, authenticated, read-only RFC 6455 telemetry stream."""
import base64
import hashlib
import json
import select
import socket
import struct
import time


def send_frame(handler, opcode, payload=b''):
    size=len(payload)
    header=bytes([0x80|opcode,size]) if size<126 else bytes([0x80|opcode,126])+struct.pack('!H',size) if size<65536 else bytes([0x80|opcode,127])+struct.pack('!Q',size)
    handler.connection.sendall(header+payload)


def stream(handler):
    if not handler.trusted_origin(required=True) or not handler.authorized():return
    if handler.browser_session is None:
        handler.reply(401,dict(ok=False,error='browser session required'));return
    try:
        key=handler.headers.get('Sec-WebSocket-Key','')
        if (handler.headers.get('Upgrade','').lower()!='websocket' or 'upgrade' not in handler.headers.get('Connection','').lower() or
            handler.headers.get('Sec-WebSocket-Version')!='13' or len(base64.b64decode(key,validate=True))!=16):raise ValueError()
    except (ValueError,TypeError):
        handler.reply(400,dict(ok=False,error='invalid WebSocket handshake'));return
    if not handler.server.websocket_slots.acquire(blocking=False):
        handler.reply(429,dict(ok=False,error='live connection budget exhausted'));return
    try:
        accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        handler.wfile.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\nCache-Control: no-store\r\n\r\n').encode());handler.wfile.flush()
        handler.connection.settimeout(1);pending=b'';next_send=0
        while not handler.server.closing.is_set():
            if handler.server.sessions.lookup(handler.cookie(),touch=False) is None:
                send_frame(handler,8,struct.pack('!H',4401)+b'session expired');return
            if time.monotonic()>=next_send:
                value=handler.server.service.handle_authenticated('control.snapshot',{},principal=handler.principal,control_token='',sessions=handler.server.sessions)
                value.pop('operator_control',None)
                raw=json.dumps(dict(type='telemetry',result=value),allow_nan=False).encode()
                if len(raw)>1_000_000:send_frame(handler,8,struct.pack('!H',1009));return
                send_frame(handler,1,raw);next_send=time.monotonic()+.5
            readable,_,_=select.select([handler.connection],[],[],.1)
            if not readable:continue
            chunk=handler.connection.recv(8192)
            if not chunk:return
            pending+=chunk
            if len(pending)>8192:send_frame(handler,8,struct.pack('!H',1009));return
            while len(pending)>=2:
                first,second=pending[:2];opcode=first&15;size=second&127
                if not first&0x80 or first&0x70 or not second&0x80 or size>125 or opcode not in (8,9,10):
                    send_frame(handler,8,struct.pack('!H',1003)+b'read-only stream');return
                if len(pending)<size+6:break
                mask=pending[2:6];payload=bytes(v^mask[i%4] for i,v in enumerate(pending[6:6+size]));pending=pending[6+size:]
                if opcode==8:send_frame(handler,8,payload);return
                if opcode==9:send_frame(handler,10,payload)
    except (OSError,ConnectionError,socket.timeout):pass
    finally:
        handler.close_connection=True;handler.server.websocket_slots.release()
