"""User-level outbound Agent; uses SSH forwarding for cross-host transport."""
import argparse
from collections import deque
import json
from pathlib import Path
import signal
from threading import Event, RLock, Thread
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from uuid import uuid4

from vehicle_autonomy.app.web.server import load_token
from .local import LocalTools
from .schema import identifier, object_fields, context, number
from .storage import Store


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Agent:
    def __init__(self, agent_id, name, role, endpoint, token, tools, *, interval_s=.5):
        identifier(agent_id)
        parts = urlsplit(endpoint)
        if parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost') or not parts.port or parts.path not in ('', '/') or parts.query or parts.fragment or parts.username is not None or parts.password is not None:
            raise ValueError('loopback HTTP endpoint required; use authenticated SSH forwarding')
        self.id = agent_id; self.name = name; self.role = role; self.endpoint = endpoint.rstrip('/')
        self.token = token; self.tools = tools; self.interval = interval_s
        self.boot = uuid4().hex; self.sequence = 0; self.stop_event = Event()
        self.pending = {}; self.completed = {}; self.inflight = set(); self.queue = deque(); self.lock = RLock()
        self.connected = False; self.error = None
        self.opener = build_opener(ProxyHandler({}),NoRedirect())
        self.thread = Thread(target=self._run, name='tool-agent-link', daemon=True)
        self.worker = Thread(target=self._commands, name='tool-agent-commands', daemon=True)

    def start(self): self.thread.start(); self.worker.start()

    def exchange(self):
        with self.lock:
            payload = dict(boot_id=self.boot, sequence=self.sequence, name=self.name, role=self.role,
                           tools=self.tools.snapshot(), results=list(self.pending.values())[:16])
            self.sequence += 1
        raw=json.dumps(payload,allow_nan=False).encode()
        if len(raw)>1_400_000:
            for report in payload['tools']:
                if report['instance']:report['instance']['logs']=report['instance']['logs'][-4:]
            raw=json.dumps(payload,allow_nan=False).encode()
        if len(raw)>1_400_000:raise ValueError('Agent metadata exceeds channel budget; split the trusted registry')
        before = time.monotonic()
        request = Request(self.endpoint + '/v1/exchange', data=raw,
            headers={'Content-Type':'application/json', 'Authorization':'Bearer ' + self.token, 'X-VAF-Agent':self.id})
        with self.opener.open(request, timeout=2) as response:
            body = response.read(262145)
        if len(body) > 262144: raise ValueError('oversized Agent response')
        result = json.loads(body)['result']; elapsed = time.monotonic() - before
        if result['boot_id'] != self.boot or result['sequence'] != payload['sequence'] or elapsed > 2:
            raise ValueError('stale/mismatched exchange response')
        with self.lock:
            for key in result['acknowledged']: self.pending.pop(key, None)
            for command in result['commands']:
                object_fields(command,('id','boot_id','operation','tool_id','profile_id','context','expires_in_s'))
                identifier(command['tool_id']);identifier(command['profile_id']);context(command['context']);number(command['expires_in_s'],0,10)
                if command['operation'] not in ('launch','stop','restart','check','connect','open'):raise ValueError('unsupported Agent command')
                if command['boot_id'] != self.boot: raise ValueError('stale command boot')
                key = command['id']; identifier(key)
                if key in self.inflight: continue
                if key in self.completed:
                    self.pending[key] = self.completed[key]; continue
                if any(c['id'] == key for c, _ in self.queue) or key in self.pending: continue
                # Executing commands also occupy a completed slot before side
                # effects, so retry cannot duplicate an in-flight command.
                if len(self.completed) + len(self.inflight) >= 4096: raise ValueError('Agent command budget exhausted')
                self.inflight.add(key)
                self.queue.append((command, time.monotonic() + max(0, min(10, command['expires_in_s']) - elapsed)))
            self.connected = True; self.error = None

    def _run(self):
        while not self.stop_event.is_set():
            try: self.exchange()
            except Exception as exc:
                error=type(exc).__name__+(f' HTTP {exc.code}' if isinstance(exc,HTTPError) else '')
                if error!=self.error:
                    try:self.tools.store.audit('agent.link_failed',error=error)
                    except OSError:pass
                    print('Tool Agent link failed: '+error+'; retrying',flush=True)
                self.connected = False; self.error = error
            self.stop_event.wait(self.interval)

    def _commands(self):
        while not self.stop_event.wait(.02):
            with self.lock: item = self.queue.popleft() if self.queue else None
            if item is None: continue
            c, deadline = item
            result = dict(id=c['id'], ok=False, result=None, error=None)
            try:
                if time.monotonic() >= deadline: raise ValueError('command expired before execution')
                result['result'] = self.tools.execute(c['operation'], c['tool_id'], c['profile_id'], c['context'])
                if type(result['result']) is dict:result['result'].pop('logs',None)
                result['ok'] = True
            except Exception as exc: result['error'] = type(exc).__name__ + ': ' + str(exc)[:500]
            with self.lock:
                self.inflight.discard(c['id']); self.completed[c['id']] = result; self.pending[c['id']] = result

    def close(self):
        self.stop_event.set(); self.thread.join(4); self.worker.join(5); self.tools.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--id', required=True); p.add_argument('--name', default='Tool Agent')
    p.add_argument('--role', choices=('desktop', 'server', 'onboard'), default='desktop')
    p.add_argument('--backend', default='http://127.0.0.1:8791')
    p.add_argument('--token-file', required=True, type=Path)
    p.add_argument('--registry', required=True, type=Path, help='trusted local Manifest JSON; never browser supplied')
    p.add_argument('--data-dir', required=True, type=Path)
    a = p.parse_args()
    # Dedicated Agent process only: adopt/reap descendants if a private
    # supervisor is killed. This is never set in the Mission/backend process.
    import ctypes
    ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)
    store = Store(a.data_dir); local = agent = None
    try:
        if a.registry.stat().st_size > 1_000_000: raise ValueError('registry too large')
        config = json.loads(a.registry.read_text()); object_fields(config, ('schema', 'tools'))
        if config['schema'] != 1: raise ValueError('registry schema 1 required')
        local = LocalTools(config['tools'], store)
        agent = Agent(a.id, a.name, a.role, a.backend, load_token(a.token_file), local)
        def stop(*_): raise KeyboardInterrupt
        signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
        agent.start()
        print(f'Tool Agent {a.id}: outbound registration to {a.backend}; no vehicle control', flush=True)
        while True: time.sleep(.5)
    except KeyboardInterrupt: pass
    finally:
        if agent: agent.close()
        elif local: local.close()
        store.close()
    return 0


if __name__ == '__main__': raise SystemExit(main())
