"""One writable workspace layout, separate from installed read-only resources."""
from pathlib import Path

from .host_environment import HostEnvironment


class RuntimePaths:
    def __init__(self, root=None):
        self.root = HostEnvironment(root).path('runtime_root')

    def slot(self, category, name=''):
        if category not in ('state', 'sessions', 'logs', 'cache'):
            raise ValueError('unknown runtime category')
        path = self.root/category/name
        if not path.resolve().is_relative_to((self.root/category).resolve()):
            raise ValueError('runtime path escapes category')
        return path
