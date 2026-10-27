"""Bounded validation of native SLAM files; no ROS or vehicle access.

The private parent is trusted same-user deployment state. A digest certifies
these bytes, not localization compatibility or the truth of a saved map.
"""
import hashlib
import os
from pathlib import Path
import re
import stat

MAX_NATIVE_FILE_BYTES = 64 * 1024 * 1024


def native_paths(directory, name):
    root = Path(directory).absolute()
    info = root.lstat()
    if (root.resolve() != root or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("explicit private owned map directory required")
    if not isinstance(name, str) or not re.fullmatch("[a-zA-Z0-9_-]{1,64}", name):
        raise ValueError("bounded map basename required")
    base = root / name
    return base, tuple(Path(str(base) + suffix) for suffix in (".posegraph", ".data"))


def prepare_native_map(directory, name):
    base, paths = native_paths(directory, name)
    if any(path.exists() or path.is_symlink() for path in paths):
        raise ValueError("refusing to overwrite existing native map evidence")
    return base, paths


def inspect_native_map(directory, name):
    _, paths = native_paths(directory, name)
    files = {}
    for path in paths:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid != os.getuid()
                    or not 0 < before.st_size <= MAX_NATIVE_FILE_BYTES):
                raise ValueError("native stored map ownership/size invalid")
            digest = hashlib.sha256()
            count = 0
            while True:
                data = os.read(fd, 65536)
                if not data:
                    break
                count += len(data)
                if count > before.st_size:
                    raise ValueError("native map changed during inspection")
                digest.update(data)
            after = os.fstat(fd)
            named = path.lstat()
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            signature = lambda info: tuple(getattr(info, field) for field in fields)
            if (count != before.st_size or signature(before) != signature(after)
                    or signature(after) != signature(named)
                    or not stat.S_ISREG(named.st_mode) or after.st_nlink != 1):
                raise ValueError("native map changed during inspection")
            files[path.name] = dict(bytes=count, sha256=digest.hexdigest())
        finally:
            os.close(fd)
    return files
