"""Authenticated MJPEG over the existing bounded HTTP server, no control ports."""
import json
import re
import socket
import time
from urllib.parse import parse_qs, urlsplit


def frame_headers(metadata, sent):
    return {'X-Camera-ID': metadata['camera_id'], 'X-Camera-Target': metadata['binding']['target'],
        'X-Camera-Epoch': metadata['binding']['epoch'], 'X-Frame-Sequence': str(metadata['sequence']),
        'X-Capture-Ns': str(metadata.get('captured_ns')), 'X-Capture-Clock': metadata['capture_clock'],
        'X-Source-Received-Ns': str(metadata['received_ns']), 'X-Web-Sent-Ns': str(sent)}


def get(handler):
    url = urlsplit(handler.path)
    if url.path != '/api/cameras' and not url.path.startswith('/api/cameras/'): return False
    if not handler.authorized(): return True
    try:
        query = parse_qs(url.query, strict_parsing=True)
        if set(query) != {'target'} or len(query['target']) != 1 or not re.fullmatch(r'[A-Za-z0-9:_.-]{1,128}', query['target'][0]):
            raise ValueError('one explicit vehicle target required; credentials in query forbidden')
        target = query['target'][0]
        manager = handler.server.service.cameras
        if url.path == '/api/cameras':
            handler.reply(200, dict(ok=True, result=dict(target=target, observed_at_ns=time.monotonic_ns(), cameras=manager.catalog(target))))
            return True
        match = re.fullmatch(r'/api/cameras/(camera-[a-f0-9]{32})/(stream|snapshot)', url.path)
        if not match: raise ValueError('unknown camera route')
        camera_id, operation = match.groups()
        metadata, jpeg = manager.packet(target, camera_id)
    except (ValueError, KeyError, OSError) as exc:
        handler.reply(409, dict(ok=False, error=str(exc)[:200])); return True
    handler.server.audit.info(json.dumps(dict(operation='camera.'+operation, camera_id=camera_id, target=target,
        epoch=metadata['binding']['epoch'], principal=handler.principal, ok=True)))
    if operation == 'snapshot':
        handler.reply(200, jpeg, 'image/jpeg', frame_headers(metadata, time.monotonic_ns()))
        return True
    if not handler.server.camera_slots.acquire(blocking=False):
        handler.reply(429, dict(ok=False, error='camera stream budget exhausted')); return True
    frames = 0
    try:
        handler.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65_536)
        handler.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        handler.connection.settimeout(.5)  # A slow reader never holds a writer or a frame queue.
        handler.send_response(200)
        for k, v in {'Content-Type':'multipart/x-mixed-replace; boundary=vaf-camera', 'Cache-Control':'no-store, private',
            'X-Content-Type-Options':'nosniff', 'X-Frame-Options':'DENY', 'Connection':'close'}.items():handler.send_header(k,v)
        handler.end_headers()
        end = time.monotonic()+60
        previous = None
        while not handler.server.closing.wait(.02) and time.monotonic()<end:
            if handler.browser_session and handler.server.sessions.lookup(handler.cookie(), touch=False) is None: break
            try: metadata, jpeg = manager.packet(target, camera_id)
            except (ValueError, KeyError, OSError): break
            if metadata['sequence'] == previous: continue
            previous = metadata['sequence']
            headers = frame_headers(metadata, time.monotonic_ns())
            headers.update({'Content-Type':'image/jpeg', 'Content-Length':str(len(jpeg))})
            handler.wfile.write(b'--vaf-camera\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers.items()).encode()+b'\r\n'+jpeg+b'\r\n')
            handler.wfile.flush(); frames += 1
    except (OSError, TimeoutError): pass
    finally:
        handler.close_connection = True
        handler.server.camera_slots.release()
        handler.server.audit.info(json.dumps(dict(operation='camera.stream.closed', camera_id=camera_id, target=target, frames=frames)))
    return True
