"""Destroy only explicitly registered, freshly created SITL session resources.

This removes logical file contents, including through an already-open fd. It
cannot promise physical erasure of SSD/COW snapshots or external backups.
No credential contents or digests of individual keys are recorded here.
"""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat


_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def identity(info):
    return {'device': info.st_dev, 'inode': info.st_ino}


class OwnedCredentials:
    def __init__(self, run_dir, manifest):
        self.root = Path(run_dir).absolute()
        self.manifest = manifest
        if self.root.resolve() != self.root:
            raise ValueError('credential root must not contain symlinks')
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('credential root is not an owned directory')
        self.root_identity = manifest.setdefault('credential_root_identity', identity(info))
        self.resources = manifest.setdefault('owned_credential_resources', [])

    @staticmethod
    def _name(name):
        if not name or Path(name).name != name or name in ('.', '..'):
            raise ValueError('credential resource must be an immediate child')
        return name

    def create_state(self, suffix):
        name = self._name('sitl_state' + suffix)
        path = self.root / name
        path.mkdir(mode=0o700)  # never adopt an existing user directory
        self.resources.append(dict(name=name, kind='directory', **identity(path.lstat())))
        return path

    def register_private(self, name, fd):
        name = self._name(name)
        info = os.fstat(fd)
        self._regular(info)
        if identity((self.root/name).lstat()) != identity(info):
            raise ValueError('private file identity changed')
        self.resources.append(dict(name=name, kind='file', **identity(info)))

    @staticmethod
    def _regular(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError('refusing non-private or multiply-linked credential file')

    def _walk(self, fd, prefix, *, destroy):
        records = []
        for name in sorted(os.listdir(fd)):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            path = prefix / name
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, _DIRECTORY, dir_fd=fd)
                try:
                    records.extend(self._walk(child, path, destroy=destroy))
                finally:
                    os.close(child)
                if destroy:
                    os.rmdir(name, dir_fd=fd)
            elif stat.S_ISLNK(info.st_mode):
                # Delete the link in our directory; never read/write its target.
                records.append(dict(path=str(path), kind='symlink', status='removed' if destroy else 'planned'))
                if destroy:
                    os.unlink(name, dir_fd=fd)
            else:
                records.append(self._file(fd, name, path, info, destroy=destroy))
        return records

    def _file(self, parent, name, path, info, *, destroy):
        self._regular(info)
        fd = os.open(name, (os.O_RDWR if destroy else os.O_RDONLY) | os.O_NOFOLLOW, dir_fd=parent)
        try:
            current = os.fstat(fd)
            self._regular(current)
            if identity(current) != identity(info):
                raise ValueError('credential file identity changed')
            digest = hashlib.sha256()
            while block := os.read(fd, 65536):
                digest.update(block)
            record = dict(path=str(path), bytes=current.st_size, sha256_before=digest.hexdigest(),
                          status='destroyed_unavailable' if destroy else 'planned')
            if destroy:
                os.lseek(fd, 0, os.SEEK_SET)
                remaining = current.st_size
                zeros = bytes(65536)
                while remaining:
                    remaining -= os.write(fd, zeros[:min(remaining, len(zeros))])
                os.fsync(fd)
                os.ftruncate(fd, 0)
                os.fsync(fd)
                os.unlink(name, dir_fd=parent)
            return record
        finally:
            os.close(fd)

    def destroy(self):
        if self.root.resolve() != self.root:
            raise ValueError('credential root replaced by symlink')
        fd = os.open(self.root, _DIRECTORY)
        try:
            if identity(os.fstat(fd)) != self.root_identity:
                raise ValueError('credential root identity changed')
            existing = []
            # Validate ALL owned resources before any destructive operation.
            for resource in self.resources:
                name = self._name(resource['name'])
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue  # idempotent close / parent crash fallback
                if identity(info) != {k: resource[k] for k in ('device', 'inode')}:
                    raise ValueError('credential resource identity changed')
                if resource['kind'] == 'directory' and stat.S_ISDIR(info.st_mode):
                    child = os.open(name, _DIRECTORY, dir_fd=fd)
                    try:
                        self._walk(child, Path(name), destroy=False)
                    finally:
                        os.close(child)
                elif resource['kind'] == 'file':
                    self._regular(info)
                else:
                    raise ValueError('credential resource type changed')
                existing.append((resource, info))
            records = self.manifest.setdefault('credential_destruction', [])
            for resource, info in existing:
                name = resource['name']
                if resource['kind'] == 'directory':
                    child = os.open(name, _DIRECTORY, dir_fd=fd)
                    try:
                        records.extend(self._walk(child, Path(name), destroy=True))
                    finally:
                        os.close(child)
                    os.rmdir(name, dir_fd=fd)
                else:
                    records.append(self._file(fd, name, Path(name), info, destroy=True))
            os.fsync(fd)
            self.manifest['credentials_removed'] = True
            self.manifest['credentials_removed_at'] = datetime.now(timezone.utc).isoformat()
        finally:
            os.close(fd)
