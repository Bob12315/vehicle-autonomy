"""Pure instance binding and loopback SITL port ownership; no World or writer."""
from __future__ import annotations

from dataclasses import dataclass
import fcntl
from pathlib import Path
import re
import socket
import xml.etree.ElementTree as ET


def instance_ports(instance: int) -> dict:
    if type(instance) is not int or not 40 <= instance <= 100:
        raise ValueError('SITL instance must be an integer in 40..100')
    return {'tcp': 5760 + 10 * instance, 'fdm': 9002 + 10 * instance,
            'udp': 5501 + 10 * instance,
            'tcp_aux': [5762 + 10 * instance, 5763 + 10 * instance]}


def bind_model(source: Path, destination: Path, *, entity_name: str, instance: int,
               system_id: int) -> dict:
    """Change only instance identity, JSON transport, and absolute topic scopes.

    Sensor extrinsics, noises, inertials, gains and all control mappings remain
    byte-equivalent XML subtrees. System ID is a SITL launch argument, never a
    mutation of the fixed default parameter files.
    """
    if not isinstance(entity_name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', entity_name):
        raise ValueError('Invalid simulation entity name')
    ports = instance_ports(instance)
    if type(system_id) is not int or system_id != instance + 1:
        raise ValueError('SITL system ID must equal instance + 1')
    tree = ET.parse(source)
    model = tree.getroot().find('model')
    if model is None:
        raise ValueError('Vehicle SDF must contain a model, never a World')
    plugins = model.findall('.//plugin[@name="ArduPilotPlugin"]')
    if len(plugins) != 1:
        raise ValueError('Exactly one ArduPilotPlugin is required')
    plugin = plugins[0]
    for key, value in [('fdm_addr', '127.0.0.1'), ('fdm_port_in', str(ports['fdm']))]:
        element = plugin.find(key)
        if element is None:
            raise ValueError('ArduPilotPlugin missing ' + key)
        element.text = value
    model.set('name', entity_name)
    topics = {}
    for element in model.iter():
        if element.tag in ('topic', 'cmd_topic', 'command_topic', 'state_topic', 'detach_topic', 'output_topic'):
            value = (element.text or '').strip()
            if value.startswith('/'):
                topics[value] = '/' + entity_name + value
                element.text = topics[value]
    tree.write(destination, encoding='utf-8', xml_declaration=True)
    return {'entity_name': entity_name, 'instance': instance, 'system_id': system_id,
            'fdm_port': ports['fdm'], 'mavlink_port': ports['tcp'],
            'internal_udp_port': ports['udp'], 'ports': ports, 'topics': topics}


@dataclass
class PortLease:
    """A cooperating process lock plus probes for every default SITL listener.

    Probe sockets are intentionally closed before SITL starts; the flock stays
    held until the caller has reaped its owned SITL. Never kills a port occupant.
    """
    instance: int
    _lock: object

    @property
    def system_id(self):
        return self.instance + 1

    @property
    def tcp_port(self):
        return instance_ports(self.instance)['tcp']

    @property
    def fdm_port(self):
        return instance_ports(self.instance)['fdm']

    @property
    def udp_port(self):
        return instance_ports(self.instance)['udp']

    @classmethod
    def acquire(cls, directory, *, minimum=40, maximum=100):
        instance_ports(minimum)
        instance_ports(maximum)
        if minimum > maximum:
            raise ValueError('Invalid instance range')
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for instance in range(minimum, maximum + 1):
            lock = (directory / f'instance-{instance}.lock').open('a+')
            sockets = []
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                ports = instance_ports(instance)
                for kind, port in [(socket.SOCK_STREAM, ports['tcp']),
                                   *[(socket.SOCK_STREAM, p) for p in ports['tcp_aux']],
                                   (socket.SOCK_DGRAM, ports['fdm']),
                                   (socket.SOCK_DGRAM, ports['udp'])]:
                    probe = socket.socket(socket.AF_INET, kind)
                    sockets.append(probe)
                    probe.bind(('127.0.0.1', port))
                return cls(instance, lock)
            except (OSError, BlockingIOError):
                lock.close()
            finally:
                for probe in sockets:
                    probe.close()
        raise RuntimeError('No unused owned loopback SITL instance is available')

    def release(self):
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    close = release

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()
