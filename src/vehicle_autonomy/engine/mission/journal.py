"""Crash-consistent Mission versions and uncertain restart records.

A lifetime flock prevents two application owners of the same journal. This is
not another vehicle authority; persistent Action providers retain their ledgers.
"""
from copy import deepcopy
import fcntl
from pathlib import Path
from vehicle_autonomy.engine.action.durable import DurableRecord, durable_directories


class MissionJournal:
    def __init__(self, path):
        self.path = Path(path).absolute()
        anchor = self.path.parent / ('.' + self.path.name + '.anchor')
        fresh = not self.path.exists() and not anchor.exists()
        if fresh:
            durable_directories(self.path)
        if not self.path.is_dir(): raise ValueError('established Mission journal missing')
        self._lock = (self.path / 'owner.lock').open('a+b')
        try: fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException: self._lock.close(); raise ValueError('Mission application already owns journal') from None
        try:
            self.record = DurableRecord(self.path / 'state.json')
            identity = {'path': str(self.path), 'inode': self.path.stat().st_ino}
            if fresh:
                DurableRecord(anchor).write(identity, create=True)
                self.record.write({'format': 1, 'versions': {}, 'runs': {}, 'manual': {}}, create=True)
            if DurableRecord(anchor).read() != identity: raise ValueError('Mission journal identity changed')
            self.data = self.record.read()
            if set(self.data) != {'format', 'versions', 'runs', 'manual'} or self.data['format'] != 1:
                raise ValueError('invalid Mission journal')
        except BaseException:
            self.close()
            raise

    def transaction(self, change):
        data = deepcopy(self.data)
        change(data)
        self.record.write(data)
        self.data = data

    def save_version(self, spec):
        d = spec.to_dict() if hasattr(spec, 'to_dict') else deepcopy(spec)
        key = d['id'] + '@' + d['version']
        def change(data):
            if key in data['versions'] and data['versions'][key] != d:
                raise ValueError('published version immutable; increment Mission version')
            if key not in data['versions'] and len(data['versions']) >= 128: raise ValueError('Mission version budget exhausted')
            data['versions'][key] = d
        self.transaction(change)
        return key

    def save_run(self, view):
        def change(data):
            if view['id'] not in data['runs'] and len(data['runs']) >= 64: raise ValueError('Mission run history budget exhausted')
            data['runs'][view['id']] = view
        self.transaction(change)

    def save_manual(self, identifier, view):
        def change(data):
            if identifier not in data['manual'] and len(data['manual']) >= 256:
                raise ValueError('manual history budget exhausted')
            data['manual'][identifier] = view
        self.transaction(change)

    def close(self):
        if getattr(self, '_lock', None) is not None:
            self._lock.close()
            self._lock = None
