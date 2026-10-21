"""Human approval of bounded designs. No vehicle, Effect or ROS capability."""
import json
import time
from threading import RLock
from uuid import uuid4

from intelligence.designs import MissionDesign


class DesignProposalService:
    def __init__(self, adapter, application, registered, *, clock=time.monotonic):
        self.adapter, self.application = adapter, application
        self.registered = frozenset(registered)
        self.clock = clock
        self.pending = {}
        self.in_flight = 0
        self.lock = RLock()

    def propose(self, text):
        with self.lock:
            if len(self.pending)+self.in_flight >= 128:
                raise ValueError('design session budget exhausted; restart and re-admit')
            self.in_flight += 1
        try:
            catalog = self.application.handle('design_catalog', {})
            capabilities = {k:v for k,v in catalog['capabilities'].items() if k in self.registered}
            # Network inference does not own either the cancel or approval lock.
            design = self.adapter.design(text, capabilities)
            design = MissionDesign.parse(json.dumps(design.document()), capabilities)
            preflight = None
            if design.decision == 'propose':
                preflight = self.application.handle('design_preflight', {
                    'design':design.document(), 'expected_context':catalog['context']})
            result = {'id':uuid4().hex, 'kind':'design', **design.document(), 'sha256':design.sha256,
                      'expires_in_s':60, 'requires_human_approval':True, 'executed':False,
                      'context':catalog['context'],
                      'preflight':preflight}
            with self.lock:
                self.pending[result['id']] = {'design':design, 'context':catalog['context'],
                    'session':catalog['session_id'], 'deadline':self.clock()+60, 'consumed':False}
            return result
        finally:
            with self.lock:
                self.in_flight -= 1

    def approve(self, identifier, human_approved):
        with self.lock:
            entry = self.pending.get(identifier)
            if human_approved is not True or entry is None:
                raise ValueError('known design and explicit human approval required')
            if entry['consumed'] or self.clock() >= entry['deadline']:
                raise ValueError('design expired or already consumed')
            if entry['design'].decision != 'propose':
                raise ValueError('clarify/reject designs cannot execute')
            # Consume before the IPC mutation; never retry an uncertain start.
            entry['consumed'] = True
            return self.application.handle('start_design_checked', {
                'design':entry['design'].document(), 'expected_context':entry['context'],
                'expected_session':entry['session']})
