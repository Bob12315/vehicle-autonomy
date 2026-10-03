"""Bounded local JSON IPC. Only the creating process removes its socket inode."""
from __future__ import annotations
import json
import os
from pathlib import Path
import selectors
import socket
import time
from uuid import uuid4

LIMIT = 8192


def socket_path(profile):
    directory = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/vaf-{os.getuid()}"))
    if not directory.exists():
        directory.mkdir(mode=0o700)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("control directory must be owned by current user and not writable by others")
    return str(directory / f"vaf-{profile}.sock")


class ControlServer:
    def __init__(self, path, service):
        self.path = Path(path)
        self.service = service
        self.selector = selectors.DefaultSelector()
        self.clients = {}
        self.cache = {}
        self.listener = socket.socket(socket.AF_UNIX)
        self.identity = None
        try:
            # bind refuses existing files and sockets; never unlink an unknown endpoint.
            self.listener.bind(str(self.path))
            self.identity = self.path.lstat().st_ino
            os.chmod(self.path, 0o600)
            self.listener.listen(16)
            self.listener.setblocking(False)
            self.selector.register(self.listener, selectors.EVENT_READ)
        except BaseException:
            self.close()
            raise

    def _drop(self, client):
        self.selector.unregister(client)
        self.clients.pop(client, None)
        client.close()

    def _response(self, raw):
        request_id = None
        try:
            request = json.loads(raw)
            if type(request) is not dict or set(request) != {"request_id", "command", "payload"}:
                raise ValueError("invalid request fields")
            request_id = request["request_id"]
            if type(request_id) is not str or not 1 <= len(request_id) <= 128:
                raise ValueError("invalid request ID")
            if type(request["command"]) is not str or type(request["payload"]) is not dict:
                raise ValueError("invalid command or payload")
            canonical = json.dumps(request, sort_keys=True)
            if request_id in self.cache:
                previous, response = self.cache[request_id]
                if previous != canonical:
                    raise ValueError("request ID reused for different content")
                return response
            # Do not evict mutation IDs: eviction could re-execute a delayed retry.
            if len(self.cache) >= 4096 and request["command"] != "status":
                raise ValueError("request cache full; restart process before further mutations")
            try:
                result = self.service.handle(request["command"], request["payload"])
                response = {"request_id": request_id, "ok": True, "result": result, "error": None}
            except (ValueError, RuntimeError) as exc:
                response = {"request_id": request_id, "ok": False, "error": str(exc)}
            if request["command"] != "status":
                self.cache[request_id] = canonical, response
            return response
        except (ValueError, TypeError, UnicodeError) as exc:
            return {"request_id": request_id, "ok": False, "error": str(exc)}

    def poll(self):
        now = time.monotonic()
        # Work is bounded per cycle; incomplete clients cannot hold the control loop.
        for key, mask in self.selector.select(0)[:32]:
            client = key.fileobj
            if client is self.listener:
                connection, _ = self.listener.accept()
                connection.setblocking(False)
                if len(self.clients) >= 16:
                    connection.close()
                    continue
                self.clients[connection] = {"in": bytearray(), "out": None, "deadline": now + 1}
                self.selector.register(connection, selectors.EVENT_READ)
                continue
            entry = self.clients[client]
            try:
                if mask & selectors.EVENT_READ:
                    chunk = client.recv(LIMIT + 1)
                    if not chunk:
                        self._drop(client)
                        continue
                    entry["in"].extend(chunk)
                    if len(entry["in"]) > LIMIT:
                        response = {"ok": False, "error": "request too long", "request_id": None}
                    elif b"\n" in entry["in"]:
                        raw, _, extra = entry["in"].partition(b"\n")
                        response = ({"ok": False, "error": "one request per connection", "request_id": None}
                                    if extra else self._response(raw))
                    else:
                        continue
                    entry["out"] = json.dumps(response).encode() + b"\n"
                    self.selector.modify(client, selectors.EVENT_WRITE)
                if mask & selectors.EVENT_WRITE:
                    count = client.send(entry["out"])
                    entry["out"] = entry["out"][count:]
                    if not entry["out"]:
                        self._drop(client)
            except (OSError, ValueError):
                if client in self.clients:
                    self._drop(client)
        for client, entry in list(self.clients.items()):
            if now >= entry["deadline"]:
                self._drop(client)

    def close(self):
        for client in list(self.clients):
            self._drop(client)
        self.listener.close()
        self.selector.close()
        if self.identity is not None:
            try:
                if self.path.lstat().st_ino == self.identity:
                    self.path.unlink()
            except FileNotFoundError:
                pass


def request(path, command, payload=None, *, request_id=None):
    data = json.dumps({"request_id": request_id or uuid4().hex, "command": command,
                       "payload": payload or {}}).encode() + b"\n"
    if len(data) > LIMIT:
        raise ValueError("request too long")
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect(str(path))
        client.sendall(data)
        result = bytearray()
        while b"\n" not in result:
            chunk = client.recv(4096)
            if not chunk:
                raise ConnectionError("control connection closed without response")
            result.extend(chunk)
            if len(result) > 2_000_000:
                raise ValueError("control response too long")
    return json.loads(result)


def run_application(profile, *, profile_name, allow_send, path):
    import signal
    from application.runtime_service import RuntimeService
    from deployment.application_runtime import ApplicationRuntime
    runtime = ApplicationRuntime(profile, profile_name=profile_name, allow_send=allow_send,
        event_sink=lambda event: print(json.dumps(event, sort_keys=True), flush=True))
    server = ControlServer(path, RuntimeService(runtime))
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, lambda *_: runtime.request_shutdown())
    try:
        while not runtime.stopping:
            started = time.monotonic()
            runtime.cycle()
            server.poll()
            time.sleep(max(0, profile.period_ns / 1e9 - (time.monotonic() - started)))
        # Flush the accepted shutdown response without running another vehicle cycle.
        until = time.monotonic() + .2
        while server.clients and time.monotonic() < until:
            server.poll()
            time.sleep(.005)
        final = runtime.shutdown()
        print(json.dumps({"final": final}, sort_keys=True), flush=True)
        return 1 if any(value == "UNCONFIRMED" for value in runtime.stops.values()) else 0
    finally:
        runtime.shutdown()
        server.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
