"""Bounded read-only camera registry; acquisition is independent of inference."""
from copy import deepcopy
import hashlib
import json
import re
from threading import RLock


class CameraSourceManager:
    def __init__(self, binding_valid=lambda binding: True):
        self.lock = RLock()
        self.sources = {}
        self.binding_valid = binding_valid
        self.closed = False

    def add_source(self, binding, slot, config, *, environment=None):
        """Trusted deployment composition only; Web never supplies device paths.

        Gazebo, USB/V4L2 and finite recordings share CameraSource. Future CSI or
        GStreamer adapters implement health/packet/close and use register().
        """
        from .live import CameraSource
        source = CameraSource(config, environment=environment)
        try: return self.register(binding, slot, source)
        except BaseException:
            source.close()
            raise

    def register(self, binding, slot, source):
        if set(binding) != {'target', 'vehicle_id', 'world', 'session', 'epoch'} or any(type(v) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',v) is None for v in binding.values()):
            raise ValueError('explicit target/vehicle/World/session/epoch required')
        if type(slot) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,128}',slot) is None:raise ValueError('bounded camera slot required')
        camera_id = 'camera-'+hashlib.sha256(json.dumps([binding, slot], sort_keys=True).encode()).hexdigest()[:32]
        with self.lock:
            if self.closed or len(self.sources) >= 16 or camera_id in self.sources:
                raise ValueError('camera registry closed, duplicate or budget exceeded')
            self.sources[camera_id] = (deepcopy(binding), slot, source)
        return camera_id

    def _entry(self, target, camera_id):
        if self.closed: raise ValueError('camera manager closed')
        binding, slot, source = self.sources[camera_id]
        if target != binding['target'] or not self.binding_valid(binding):
            raise ValueError('camera target or instance epoch no longer active')
        return binding, slot, source

    def catalog(self, target):
        if type(target) is not str or not target: raise ValueError('explicit camera target required')
        result = []
        with self.lock:
            for camera_id, (binding, slot, source) in self.sources.items():
                if target != binding['target'] or self.closed or not self.binding_valid(binding): continue
                result.append(dict(camera_id=camera_id, slot=slot, binding=deepcopy(binding), **source.health()))
        return result

    def packet(self, target, camera_id):
        with self.lock:
            binding, _, source = self._entry(target, camera_id)
            metadata, jpeg = source.packet()
            self._entry(target, camera_id)
            return dict(metadata, camera_id=camera_id, binding=deepcopy(binding)), jpeg

    def retire(self, target):
        with self.lock:
            entries = [self.sources.pop(k) for k, v in list(self.sources.items()) if v[0]['target']==target]
        for _, _, source in entries: source.close()

    def close(self):
        with self.lock:
            self.closed = True
            entries, self.sources = list(self.sources.values()), {}
        errors = []
        for _, _, source in entries:
            try: source.close()
            except Exception as exc: errors.append(str(exc))
        if errors: raise RuntimeError('camera cleanup unconfirmed: '+'; '.join(errors))
