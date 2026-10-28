"""Private state, bounded audit, atomic configuration; never serves arbitrary files."""
from collections import deque
from datetime import datetime, timezone
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import stat
from threading import RLock
from uuid import uuid4


class AuditHandler(RotatingFileHandler):
    def _open(self):
        descriptor=os.open(self.baseFilename,os.O_APPEND|os.O_CREAT|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        return os.fdopen(descriptor,'a',encoding='utf-8')

    def handleError(self,record):
        # Python logging otherwise swallows disk/rotation errors, which would
        # permit an unaudited new process launch. Admission must fail closed.
        raise OSError('tool audit write failed') from None


class Store:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('owned private state directory required (0700)')
        self.lock_fd = os.open(self.root / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try: fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.lock_fd); raise ValueError('state directory already in use') from None
        self.lock = RLock(); self.events = deque(maxlen=300)
        self.logger = logging.getLogger('vaf.tools.' + uuid4().hex)
        self.logger.setLevel(logging.INFO); self.logger.propagate = False
        path = self.root / 'audit.jsonl'
        if path.is_symlink(): self.close(); raise ValueError('audit symlink rejected')
        try:
            self.handler = AuditHandler(path, maxBytes=1_000_000, backupCount=3)
            os.chmod(path, 0o600); self.logger.addHandler(self.handler)
        except BaseException:self.close();raise

    def load(self, name, default):
        with self.lock:
            path = self.root / name
            if path.is_symlink(): raise ValueError('state symlink rejected')
            if not path.exists(): return default
            if path.stat().st_size > 2_000_000: raise ValueError('state file too large')
            return json.loads(path.read_text())

    def save(self, name, value):
        with self.lock:
            path = self.root / name
            if path.is_symlink(): raise ValueError('state symlink rejected')
            temporary = self.root / ('.pending-' + uuid4().hex)
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    json.dump(value, stream, allow_nan=False); stream.flush(); os.fsync(stream.fileno())
                os.replace(temporary, path)
                fd = os.open(self.root, os.O_DIRECTORY)
                try: os.fsync(fd)
                finally: os.close(fd)
            finally:
                temporary.unlink(missing_ok=True)

    def audit(self, operation, **fields):
        with self.lock:
            event = dict(at=datetime.now(timezone.utc).isoformat(), operation=operation, **fields)
            self.logger.info(json.dumps(event, ensure_ascii=True, allow_nan=False))
            self.events.append(event)

    def close(self):
        if getattr(self, 'handler', None):
            self.logger.removeHandler(self.handler); self.handler.close(); self.handler = None
        if getattr(self, 'lock_fd', None) is not None:
            os.close(self.lock_fd); self.lock_fd = None
