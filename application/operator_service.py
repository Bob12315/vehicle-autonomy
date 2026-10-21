"""Operator use cases and saved map previews, with an injected Application API."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import threading

from mapping.grid import MapStore, OccupancyGrid


class OperatorService:
    def __init__(self, application, data_dir, *, llm=None, missions=()):
        self.application = application
        self.directory = Path(data_dir)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.maps = MapStore(self.directory / 'maps')
        self.missions = tuple(missions)
        self.lock = threading.RLock()
        self.waypoints = {}
        waypoint_file = self.directory / 'waypoints.json'
        if waypoint_file.is_file() and waypoint_file.stat().st_size <= 65536:
            self.waypoints = json.loads(waypoint_file.read_text())
        self.designs = None
        self.proposals = None
        if llm is not None:
            from application.proposals import ProposalService
            self.proposals = ProposalService(llm, application, missions)
            from application.design_proposals import DesignProposalService
            self.designs = DesignProposalService(llm, application, missions)

    def handle(self, operation, payload):
        if operation in ('status', 'camera', 'map', 'reports'):
            if payload:
                raise ValueError('read use case takes no payload')
            return self.application.handle(operation, {})
        if operation in ('propose','design'):
            if self.proposals is None:
                raise ValueError('LLM is not configured; local application remains independent')
            if set(payload) != {'text'}:
                raise ValueError('proposal requires only text')
            # A remote model must never hold the operator mutation/cancel lock.
            return (self.designs if operation=='design' else self.proposals).propose(payload['text'])
        with self.lock:
            if operation == 'start':
                if set(payload) != {'mission','expected_session'} or payload['mission'] not in self.missions:
                    raise ValueError('choose an explicitly registered operator mission')
                state = self.application.handle('status', {})
                if type(payload['expected_session']) is not str or payload['expected_session'] != state.get('session_id'):
                    raise ValueError('application session changed; refresh and authorize a new request')
                return self.application.handle('start_checked', payload)
            if operation == 'cancel':
                if payload:
                    raise ValueError('cancel takes no payload')
                return self.application.handle('cancel', {})
            if operation == 'waypoint':
                if (set(payload) != {'name','x','y','frame'} or type(payload['name']) is not str
                        or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,47}',payload['name']) is None
                        or payload['frame'] not in ('map','odom')
                        or any(type(payload[k]) not in (float,int) or not math.isfinite(payload[k]) or abs(payload[k])>10000 for k in ('x','y'))):
                    raise ValueError('invalid finite named waypoint')
                if len(self.waypoints) >= 64 and payload['name'] not in self.waypoints:
                    raise ValueError('waypoint budget exhausted')
                self.waypoints[payload['name']] = {**payload, 'status':'DRAFT', 'control_eligible':False}
                from mapping.grid import atomic_json
                atomic_json(self.directory / 'waypoints.json', self.waypoints)
                return self.waypoints[payload['name']]
            if operation == 'waypoints':
                if payload:
                    raise ValueError('waypoints takes no payload')
                return dict(self.waypoints)
            if operation == 'save_map':
                if payload:
                    raise ValueError('save map takes no payload')
                current = self.application.handle('map', {})
                grid = OccupancyGrid.from_document(json.loads(json.dumps(current['grid'])))
                digest = self.maps.save(grid)
                self.maps.export_pgm(digest, self.directory / 'exports' / digest)
                return {'sha256':digest,'saved':True,'control_eligible':False}
            if operation == 'load_map':
                if set(payload) != {'sha256'}:
                    raise ValueError('load preview requires content hash')
                grid = self.maps.load(payload['sha256'])
                return {'grid':grid.document(),'source':'saved_preview','control_eligible':False,
                        'reason':'preview only; stop/restart mapping, localization and new anchor admission required'}
            if operation in ('approve','approve_design'):
                if self.proposals is None or set(payload) != {'id','human_approved'}:
                    raise ValueError('known proposal and explicit human approval required')
                return (self.designs if operation=='approve_design' else self.proposals).approve(payload['id'],payload['human_approved'])
        raise ValueError('unknown operator use case')
