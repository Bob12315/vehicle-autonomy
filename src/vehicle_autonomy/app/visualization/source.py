"""Bounded HTTP reader/proposal uploader. No vehicle or command endpoint."""
from collections import deque
import json
from pathlib import Path
from threading import Event,Lock,Thread
import time
from urllib.parse import urlencode
from urllib.request import Request,build_opener,HTTPRedirectHandler,ProxyHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kw):return None  # Never forward a credential to another origin.


class Client:
    def __init__(self,config,target):
        self.config=config;self.target=target;self.credential=Path(config['token_file']).read_text().strip()
        if not 32<=len(self.credential)<=256:raise ValueError('invalid visualization credential')
        self.http=build_opener(ProxyHandler({}),NoRedirect())

    def request(self,path,payload=None):
        headers={'Authorization':'Bearer '+self.credential}
        body=None
        if payload is not None:headers.update({'Content-Type':'application/json','X-VAF-Visualization':'candidate-v1'});body=json.dumps(payload,allow_nan=False).encode()
        with self.http.open(Request(self.config['url']+path,body,headers),timeout=.4) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('visualization response budget exceeded')
            value=json.loads(raw)
            if not value.get('ok'):raise ValueError('Framework visualization request rejected')
            return value['result']


class Source(Client):
    def __init__(self,config,target):
        super().__init__(config,target)
        self.latest=None;self.error='waiting for Framework';self.proposal_result=None;self.proposals=deque(maxlen=8);self.lock=Lock();self.closed=Event()
        self.thread=Thread(target=self._run,name='visualization-source',daemon=True);self.thread.start()

    def enqueue(self,payload):
        with self.lock:
            if len(self.proposals)==self.proposals.maxlen:raise ValueError('proposal queue full')
            self.proposals.append(payload)

    def read(self):
        with self.lock:return self.latest,self.error,self.proposal_result

    def _run(self):
        while not self.closed.is_set():
            started=time.monotonic_ns()
            try:
                value=self.request('/api/visualization/state?'+urlencode(dict(target=self.target)))
                received=time.monotonic_ns()
                with self.lock:self.latest=(value,received,(received-started)/1e9);self.error=None;proposal=self.proposals.popleft() if self.proposals else None
                if proposal is not None:
                    try:result=dict(ok=True,id=self.request('/api/visualization/candidates',proposal)['id'])
                    except Exception as exc:result=dict(ok=False,error=type(exc).__name__+'; proposal not confirmed')
                    with self.lock:self.proposal_result=result
            except Exception as exc:
                with self.lock:self.error=type(exc).__name__+'; Framework feed unavailable'  # No credential/URL/response body in logs.
            self.closed.wait(max(0,.1-(time.monotonic_ns()-started)/1e9))

    def close(self):
        self.closed.set();self.thread.join(1.5)
        if self.thread.is_alive():raise RuntimeError('visualization source worker did not stop')
