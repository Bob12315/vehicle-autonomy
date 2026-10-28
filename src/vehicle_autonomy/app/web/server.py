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
import re
import stat
import threading
import ssl
from http.cookies import SimpleCookie, CookieError
from urllib.parse import urlsplit, quote

from .auth import BrowserSessions


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
        self.secure_cookies=False;self.browser_origin=None
        self.visualization_token=None
        self.sessions=BrowserSessions()
        self.websocket_slots=threading.BoundedSemaphore(4)
        self.closing=threading.Event()
        self.slots = threading.BoundedSemaphore(12)
        self.requests = {}
        self.request_lock = threading.RLock()
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
        self.closing.set()
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

    def reply(self, code, body, content_type='application/json', headers=None):
        raw = json.dumps(body, allow_nan=False).encode() if content_type == 'application/json' else body
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        for key,value in (headers or {}).items():self.send_header(key,value)
        self.end_headers()
        self.wfile.write(raw)

    def trusted_origin(self, *, required=False):
        port = self.server.server_address[1]
        host = self.headers.get('Host','')
        allowed_hosts = (f'127.0.0.1:{port}',f'localhost:{port}')
        origin = self.headers.get('Origin')
        scheme='https' if self.server.secure_cookies or isinstance(self.connection,ssl.SSLSocket) else 'http'
        expected=self.server.browser_origin or scheme+'://'+host
        if host not in allowed_hosts or (required and origin is None) or (origin is not None and origin!=expected):
            self.reply(403,{'ok':False,'error':'untrusted Host/Origin'})
            return False
        return True

    @property
    def cookie_name(self):return 'vaf_session_'+str(self.server.server_address[1])

    def cookie(self):
        try:
            cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''))
            return cookie[self.cookie_name].value if self.cookie_name in cookie else ''
        except CookieError:return ''

    def cookie_header(self, opaque='', *, clear=False):
        value=f'{self.cookie_name}={opaque}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else self.server.sessions.lifetime_s}'
        if self.server.secure_cookies or isinstance(self.connection,ssl.SSLSocket):value+='; Secure'
        return value

    def authorized(self, mutation=False):
        if not self.trusted_origin():return False
        self.browser_session=None;self.principal='api';self.control_token=self.headers.get('X-VAF-Control','')
        supplied = self.headers.get('Authorization','')
        if supplied:
            if not self.server.token or not hmac.compare_digest(supplied.encode(),('Bearer '+self.server.token).encode()):
                self.reply(401,{'ok':False,'error':'authentication required'});return False
            csrf=self.server.token
        else:
            self.browser_session=self.server.sessions.lookup(self.cookie())
            if self.browser_session is None:
                self.reply(401,{'ok':False,'error':'session expired or authentication required'});return False
            self.principal=self.browser_session.principal;csrf=self.browser_session.csrf
        if mutation and not hmac.compare_digest(self.headers.get('X-VAF-CSRF','').encode(),csrf.encode()):
            self.reply(403,{'ok':False,'error':'custom CSRF header required'});return False
        return True

    def page_authorized(self):
        if not self.trusted_origin():return False
        supplied=self.headers.get('Authorization','')
        if self.server.sessions.lookup(self.cookie()) or self.server.token and hmac.compare_digest(supplied.encode(),('Bearer '+self.server.token).encode()):return True
        self.reply(302,b'','text/plain',{'Location':'/login?next='+quote(self.path,safe='')})
        return False

    def auth_get(self):
        path=urlsplit(self.path).path
        assets={'/login':('login.html','text/html; charset=utf-8'),'/auth.js':('auth.js','application/javascript'),
                '/login.js':('login.js','application/javascript'),'/login.css':('login.css','text/css'),'/tool-console.css':('tool-console.css','text/css')}
        if path in assets:
            if not self.trusted_origin():return True
            name,kind=assets[path];self.reply(200,(Path(__file__).parent/'static'/name).read_bytes(),kind);return True
        if path=='/api/auth/session':
            if self.authorized():
                if self.browser_session:self.reply(200,dict(ok=True,result=self.server.sessions.view(self.browser_session)))
                else:self.reply(401,dict(ok=False,error='browser login required'))
            return True
        return False

    def auth_post(self):
        if self.path not in ('/api/auth/login','/api/auth/logout'):return False
        if not self.trusted_origin(required=True):return True
        if self.path=='/api/auth/logout':
            if not self.authorized(mutation=True):return True
            session=self.server.sessions.revoke(self.cookie())
            release=getattr(self.server.service,'release_browser',None)
            if session and callable(release):release(session.principal)
            self.reply(200,dict(ok=True,result=dict(logged_out=True)),headers={'Set-Cookie':self.cookie_header(clear=True)})
            return True
        try:
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type')!='application/json':raise ValueError()
            length=int(self.headers.get('Content-Length','-1'))
            if not 0<length<=1024:raise ValueError()
            payload=json.loads(self.rfile.read(length))
            if type(payload) is not dict or set(payload)!={'key'} or type(payload['key']) is not str or not 32<=len(payload['key'])<=256:raise ValueError()
        except (ValueError,TypeError):
            self.reply(400,dict(ok=False,error='bounded login key required'));return True
        if not self.server.sessions.permitted_login(self.client_address[0]):
            self.reply(429,dict(ok=False,error='login rate limit; retry later'));return True
        if not self.server.token or not hmac.compare_digest(payload['key'].encode(),self.server.token.encode()):
            self.server.sessions.failed_login(self.client_address[0])
            self.reply(401,dict(ok=False,error='invalid login key'));return True
        old=self.server.sessions.revoke(self.cookie())
        release=getattr(self.server.service,'release_browser',None)
        if old and callable(release):release(old.principal)
        try:opaque,session=self.server.sessions.create()
        except ValueError:
            self.reply(429,dict(ok=False,error='browser session budget exhausted'));return True
        self.server.audit.info(json.dumps(dict(operation='browser.login',ok=True)))
        self.reply(200,dict(ok=True,result=self.server.sessions.view(session)),headers={'Set-Cookie':self.cookie_header(opaque)})
        return True

    def do_GET(self):
        if self.auth_get():return
        static = {'/':('index.html','text/html; charset=utf-8'),
                  '/console.js':('console.js','application/javascript'),
                  '/console.css':('console.css','text/css')}
        if self.path in static:
            name, content_type = static[self.path]
            if name.endswith('.html') and not self.page_authorized():return
            self.reply(200,(Path(__file__).parent / 'static' / name).read_bytes(),content_type)
            return
        if not self.authorized():
            return
        routes = {'/api/status':'status','/api/map':'map','/api/camera':'camera','/api/waypoints':'waypoints',
                  '/api/reports':'reports'}
        if self.path == '/api/catalog':
            self.reply(200,{'ok':True,'result':list(self.server.service.missions)})
            return
        if self.path not in routes:
            self.reply(404,{'ok':False,'error':'unknown route'})
            return
        self.invoke(routes[self.path],{})

    def do_POST(self):
        if self.auth_post():return
        if not self.authorized(mutation=True):
            return
        routes = {'/api/start':'start','/api/cancel':'cancel','/api/waypoint':'waypoint',
                  '/api/map/save':'save_map','/api/map/load':'load_map',
                  '/api/propose':'propose','/api/approve':'approve',
                  '/api/design':'design','/api/design/approve':'approve_design'}
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
        if operation in ('start','approve','approve_design','cancel'):
            identifier = self.headers.get('X-VAF-Request-ID','')
            if re.fullmatch(r'[A-Za-z0-9:_-]{1,128}',identifier) is None:
                self.reply(400,{'ok':False,'error':'bounded mutation request ID required'})
                return
            canonical=json.dumps([operation,payload],sort_keys=True,allow_nan=False)
            identifier=(self.principal,identifier)
            with self.server.request_lock:
                if identifier in self.server.requests:
                    old,code,response=self.server.requests[identifier]
                    if old!=canonical:
                        self.reply(409,{'ok':False,'error':'request ID reused with different content'})
                    else:self.reply(code,response)
                    return
                if len(self.server.requests)>=4096:
                    self.reply(409,{'ok':False,'error':'mutation budget exhausted; restart console and re-admit'})
                    return
                code,response=self.invoke(operation,payload,mutation=True,send=False)
                self.server.requests[identifier]=canonical,code,response
                self.reply(code,response)
            return
        self.invoke(operation,payload,mutation=True)

    def invoke(self, operation, payload, mutation=False, send=True):
        try:
            authenticated=getattr(self.server.service,'handle_authenticated',None)
            if callable(authenticated):
                result=authenticated(operation,payload,principal=getattr(self,'principal','api'),
                    control_token=getattr(self,'control_token',''),sessions=self.server.sessions)
            else:result = self.server.service.handle(operation,payload)
            response = {'ok':True,'result':result}
            code = 200
        except Exception as exc:
            response = {'ok':False,'error':f'{type(exc).__name__}: {str(exc)[:500]}'}
            code = 409
        if mutation:
            self.server.audit.info(json.dumps({'operation':operation,'ok':response['ok'],
                'peer':self.client_address[0], 'request_id':secrets.token_hex(8),
                'mission':payload.get('mission') if operation=='start' else None,
                'proposal_id':payload.get('id') if operation in ('approve','approve_design') else None,
                'task_id':(response.get('result') or {}).get('task_id') if type(response.get('result')) is dict else None}))
        if send:self.reply(code,response)
        return code,response
