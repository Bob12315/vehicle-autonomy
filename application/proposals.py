"""Human-approved, session-bound proposals through Application use cases only."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import time
from threading import RLock
from uuid import uuid4


def context_key(state):
    # Revisions evolve during normal telemetry. Epochs and environment identity may not.
    return hashlib.sha256(json.dumps({'session': state.get('session_id'),
        'generation': (state.get('world_version') or {}).get('generation'),
        'environment': state.get('environment'), 'profile': state.get('profile')}, sort_keys=True).encode()).hexdigest()


class ProposalService:
    def __init__(self, adapter, application, registered, *, clock=time.monotonic):
        self.adapter, self.application = adapter, application
        self.registered = tuple(registered)
        self.clock = clock
        self.pending = {}
        self.lock = RLock()
        self.in_flight = 0

    def propose(self, text):
        with self.lock:
            if len(self.pending) + self.in_flight >= 256:
                raise ValueError('proposal session budget exhausted; restart operator console')
            self.in_flight += 1
        try:
            state = self.application.handle('status', {})
            proposal = self.adapter.propose(text, self.registered)
            identifier = uuid4().hex
            result = {'id': identifier, **asdict(proposal), 'expires_in_s': 60,
                      'requires_human_approval': True, 'executed': False}
            with self.lock:
                self.pending[identifier] = {'result': result, 'context': context_key(state),
                                           'deadline': self.clock() + 60, 'consumed': False}
            return result
        finally:
            with self.lock:
                self.in_flight -= 1

    def approve(self, identifier, human_approved):
        with self.lock:
            return self._approve(identifier, human_approved)

    def _approve(self, identifier, human_approved):
        entry = self.pending.get(identifier)
        if human_approved is not True or entry is None:
            raise ValueError('explicit human approval of a known proposal required')
        if entry['consumed'] or self.clock() >= entry['deadline']:
            raise ValueError('proposal expired or already consumed')
        result = entry['result']
        if result['decision'] != 'propose' or result['mission'] not in self.registered:
            raise ValueError('proposal is not executable')
        state = self.application.handle('status', {})
        if context_key(state) != entry['context'] or state.get('state') != 'READY':
            raise ValueError('environment/session changed or application not READY')
        if state.get('mode') == 'hardware_readonly' or not state.get('profile', '').endswith('_sim'):
            raise ValueError('hardware motion remains disabled pending onsite acceptance')
        # Consume before mutation; a transport timeout must not trigger a blind retry.
        entry['consumed'] = True
        return self.application.handle('start', {'mission': result['mission']})
