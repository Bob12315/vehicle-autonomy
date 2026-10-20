"""Loopback HTTP console; authentication and custom-header CSRF protection."""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import stat
import threading


def load_token(path):
    path = Path(path)
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(secrets.token_urlsafe(32) + '\n')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('token must be an owned private regular file (0600)')
    token = path.read_text().strip()
    if len(token) < 32 or len(token) > 256:
        raise ValueError('strong bounded token required')
    return token


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    # SO_REUSEADDR permits a stopped server's TIME_WAIT sockets, without
    # SO_REUSEPORT or sharing a live listener with another process.
    allow_reuse_address = True

    def __init__(self, address, service, token, audit_path):
        if address[0] not in ('127.0.0.1','::1'):
            raise ValueError('console must bind loopback; use an authenticated SSH tunnel')
        self.service, self.token = service, token
        self.slots = threading.BoundedSemaphore(12)
        self.audit = logging.getLogger('vaf.web.' + secrets.token_hex(8))
        self.audit.setLevel(logging.INFO)
        self.audit.propagate = False
        self.audit_handler = RotatingFileHandler(audit_path, maxBytes=2_000_000, backupCount=3)
        self.audit.addHandler(self.audit_handler)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request,address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request,address)
        finally:
            self.slots.release()

    def server_close(self):
        super().server_close()
        self.audit.removeHandler(self.audit_handler)
        self.audit_handler.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self,*args):
        pass  # Do not place user input, tokens or arbitrary URL paths into logs.

    def reply(self, code, body, content_type='application/json'):
        raw = json.dumps(body, allow_nan=False).encode() if content_type == 'application/json' else body
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self, mutation=False):
        port = self.server.server_address[1]
        host = self.headers.get('Host','')
        allowed_hosts = (f'127.0.0.1:{port}',f'localhost:{port}')
        origin = self.headers.get('Origin')
        if host not in allowed_hosts or (origin is not None and origin not in tuple('http://'+h for h in allowed_hosts)):
            self.reply(403,{'ok':False,'error':'untrusted Host/Origin'})
            return False
        supplied = self.headers.get('Authorization','')
        if not hmac.compare_digest(supplied.encode(),('Bearer '+self.server.token).encode()):
            self.reply(401,{'ok':False,'error':'authentication required'})
            return False
        if mutation and not hmac.compare_digest(self.headers.get('X-VAF-CSRF','').encode(),self.server.token.encode()):
            self.reply(403,{'ok':False,'error':'custom CSRF header required'})
            return False
        return True

    def do_GET(self):
        static = {'/':('index.html','text/html; charset=utf-8'),
                  '/console.js':('console.js','application/javascript'),
                  '/console.css':('console.css','text/css')}
        if self.path in static:
            name, content_type = static[self.path]
            self.reply(200,(Path(__file__).parent / 'static' / name).read_bytes(),content_type)
            return
        if not self.authorized():
            return
        routes = {'/api/status':'status','/api/map':'map','/api/camera':'camera','/api/waypoints':'waypoints'}
        if self.path == '/api/catalog':
            self.reply(200,{'ok':True,'result':list(self.server.service.missions)})
            return
        if self.path not in routes:
            self.reply(404,{'ok':False,'error':'unknown route'})
            return
        self.invoke(routes[self.path],{})

    def do_POST(self):
        if not self.authorized(mutation=True):
            return
        routes = {'/api/start':'start','/api/cancel':'cancel','/api/waypoint':'waypoint',
                  '/api/map/save':'save_map','/api/map/load':'load_map',
                  '/api/propose':'propose','/api/approve':'approve'}
        operation = routes.get(self.path)
        try:
            if operation is None or self.headers.get('Transfer-Encoding'):
                raise ValueError('unsupported route or transfer encoding')
            if self.headers.get('Content-Type') != 'application/json':
                raise ValueError('JSON content type required')
            length = int(self.headers.get('Content-Length','-1'))
            if not 0 <= length <= 8192:
                raise ValueError('bounded Content-Length required')
            payload = json.loads(self.rfile.read(length),parse_constant=lambda _: (_ for _ in ()).throw(ValueError('finite JSON required')))
            if type(payload) is not dict:
                raise ValueError('JSON object required')
        except (ValueError,TypeError) as exc:
            self.reply(400,{'ok':False,'error':str(exc)})
            return
        self.invoke(operation,payload,mutation=True)

    def invoke(self, operation, payload, mutation=False):
        try:
            result = self.server.service.handle(operation,payload)
            response = {'ok':True,'result':result}
            code = 200
        except Exception as exc:
            response = {'ok':False,'error':f'{type(exc).__name__}: {str(exc)[:500]}'}
            code = 409
        if mutation:
            self.server.audit.info(json.dumps({'operation':operation,'ok':response['ok'],
                'peer':self.client_address[0], 'request_id':secrets.token_hex(8),
                'mission':payload.get('mission') if operation=='start' else None,
                'proposal_id':payload.get('id') if operation=='approve' else None,
                'task_id':(response.get('result') or {}).get('task_id') if type(response.get('result')) is dict else None}))
        self.reply(code,response)
