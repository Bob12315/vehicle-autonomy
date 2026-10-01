"""Transparent frame forwarding and connection-scoped fault controls."""
from pathlib import Path
import socket
import tempfile
import unittest
from pymavlink.dialects.v20 import ardupilotmega as mav
from tests.simulation.faults import TcpFaultProxy


class ProxyTests(unittest.TestCase):
    def receive(self, connection, count):
        data = b''
        while len(data) < count:
            chunk = connection.recv(count - len(data))
            if not chunk:
                raise AssertionError('unexpected proxy EOF')
            data += chunk
        return data

    def test_forward_filter_delay_and_discard_old_epoch_bytes(self):
        sender = mav.MAVLink(None, srcSystem=1, srcComponent=1)
        hb = sender.heartbeat_encode(2, 3, 0, 4, 4).pack(sender)
        pose = sender.attitude_encode(1000, 0, 0, 0, 0, 0, 0).pack(sender)
        ack_mode = sender.command_ack_encode(176, 0).pack(sender)
        ack_arm = sender.command_ack_encode(400, 0).pack(sender)
        with tempfile.TemporaryDirectory() as directory, socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen(2)
            server.settimeout(2)
            proxy = TcpFaultProxy(server.getsockname()[1], Path(directory) / 'proxy.jsonl')
            client = upstream = second = new_upstream = None
            try:
                client = socket.create_connection(('127.0.0.1', proxy.port), timeout=2)
                upstream, _ = server.accept()
                upstream.settimeout(2)
                upstream.sendall(hb)
                self.assertEqual(self.receive(client, len(hb)), hb)
                client.sendall(ack_arm)
                self.assertEqual(self.receive(upstream, len(ack_arm)), ack_arm)
                proxy.inject(drop_rx={'HEARTBEAT'}, drop_ack_command=176)
                upstream.sendall(hb + ack_mode + ack_arm)
                self.assertEqual(self.receive(client, len(ack_arm)), ack_arm)
                proxy.inject(drop_rx=set(), drop_ack_command=None, delay_pose_s=.2)
                upstream.sendall(pose)
                client.settimeout(.05)
                with self.assertRaises(socket.timeout):
                    client.recv(4096)
                client.settimeout(2)
                self.assertEqual(self.receive(client, len(pose)), pose)
                proxy.inject(delay_pose_s=1)
                upstream.sendall(pose)
                proxy.disconnect()
                self.assertEqual(client.recv(4096), b'')
                second = socket.create_connection(('127.0.0.1', proxy.port), timeout=2)
                new_upstream, _ = server.accept()
                new_upstream.sendall(hb)
                self.assertEqual(self.receive(second, len(hb)), hb)
                second.settimeout(1.2)
                with self.assertRaises(socket.timeout):
                    second.recv(4096)
                self.assertIsNone(proxy.error)
                self.assertEqual(len(proxy.tx()), 1)
            finally:
                proxy.close()
                for connection in (client, upstream, second, new_upstream):
                    if connection is not None:
                        connection.close()
