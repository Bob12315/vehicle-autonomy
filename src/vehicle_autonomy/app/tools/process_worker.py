"""Private supervisor. Parent pipe loss cleans only this tool's process group.

The worker is a Linux subreaper so orphaned grandchildren can be reaped. Tools
must remain in their process group (daemonizing/session-escaping tools are not
supported). No parent-death preexec callback is used in the multithreaded Agent.
"""
import ctypes
import json
import os
import selectors
import signal
import subprocess
import sys
import time


def main():
    ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
    config = json.loads(sys.stdin.buffer.readline(262144))
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    def emit(**value):
        nonlocal stopping
        try: print(json.dumps(value), flush=True)
        except (BrokenPipeError, OSError): stopping = True
    process = None
    try:
        process = subprocess.Popen(config['argv'], env=config['env'], cwd=config['cwd'],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        emit(event='spawned', pid=process.pid)
        selector = selectors.DefaultSelector()
        selector.register(sys.stdin.buffer, selectors.EVENT_READ, 'parent')
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ, 'log')
        while not stopping and process.poll() is None:
            for key, _ in selector.select(.05):
                if key.data == 'parent':
                    # Any explicit byte, or EOF when the Agent dies, means stop.
                    os.read(sys.stdin.fileno(), 4096); stopping = True
                else:
                    data = os.read(process.stdout.fileno(), 2048)
                    if data: emit(event='log', text=data.decode(errors='replace'))
                    else: selector.unregister(process.stdout)
        selector.close()
    except Exception as exc:
        emit(event='error', error=type(exc).__name__ + ': ' + str(exc)[:400])
    finally:
        clean = True
        if process:
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            end = time.monotonic() + config['stop_timeout_s']
            while time.monotonic() < end:
                process.poll()
                try:
                    while os.waitpid(-1, os.WNOHANG)[0]: pass
                except ChildProcessError: break
                time.sleep(.02)
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: clean = False
            end = time.monotonic() + 2
            while time.monotonic() < end:
                try:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                    if pid == 0: time.sleep(.02)
                except ChildProcessError: break
            try: os.killpg(process.pid, 0); clean = False
            except ProcessLookupError: pass
            process.stdout.close()
        emit(event='exit', returncode=None if process is None else process.returncode, cleanup_confirmed=clean)
    return 0


if __name__ == '__main__': raise SystemExit(main())
