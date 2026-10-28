"""Browser sessions, separate from the existing operator/Agent credentials."""
from dataclasses import dataclass
import hashlib
import secrets
from threading import RLock
import time


@dataclass
class BrowserSession:
    principal: str
    csrf: str
    created: float
    seen: float


class BrowserSessions:
    def __init__(self, *, idle_s=1800, lifetime_s=28800, clock=time.monotonic):
        self.idle_s=idle_s;self.lifetime_s=lifetime_s;self.clock=clock
        self.lock=RLock();self.records={};self.failures={}

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def valid(self, session):
        now=self.clock()
        return 0<=now-session.seen<self.idle_s and 0<=now-session.created<self.lifetime_s

    def create(self):
        now=self.clock();opaque=secrets.token_urlsafe(32)
        session=BrowserSession('web:'+secrets.token_hex(16),secrets.token_urlsafe(24),now,now)
        with self.lock:
            self.records={k:v for k,v in self.records.items() if self.valid(v)}
            if len(self.records)>=128:raise ValueError('browser session budget exhausted')
            self.records[self.digest(opaque)]=session
        return opaque,session

    def lookup(self, opaque, *, touch=True):
        if not opaque or len(opaque)>128:return None
        with self.lock:
            key=self.digest(opaque);session=self.records.get(key)
            if session is None:return None
            if not self.valid(session):self.records.pop(key,None);return None
            if touch:session.seen=self.clock()
            return session

    def alive(self, principal):
        with self.lock:return any(s.principal==principal and self.valid(s) for s in self.records.values())

    def revoke(self, opaque):
        with self.lock:return self.records.pop(self.digest(opaque),None)

    def permitted_login(self, peer):
        with self.lock:
            times=[t for t in self.failures.get(peer,[]) if self.clock()-t<60]
            self.failures[peer]=times
            return len(times)<10

    def failed_login(self, peer):
        with self.lock:self.failures.setdefault(peer,[]).append(self.clock())

    def view(self, session):
        return dict(authenticated=True,principal=session.principal,csrf=session.csrf,
                    idle_timeout_s=self.idle_s,remaining_s=max(0,int(min(
                        self.lifetime_s-(self.clock()-session.created),self.idle_s-(self.clock()-session.seen)))))
