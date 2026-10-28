"""Read-only local listener discovery; does not connect to a vehicle endpoint."""
from pathlib import Path
import sys


def main():
    port = int(sys.argv[1])
    if not 1024 <= port <= 65535: raise ValueError('bounded local simulator port required')
    for source in ('/proc/net/tcp','/proc/net/tcp6'):
        for line in Path(source).read_text().splitlines()[1:]:
            fields=line.split()
            if int(fields[1].split(':')[-1],16)==port and fields[3]=='0A':
                print('LISTEN (socket availability only, not telemetry qualification)');return 0
    return 2


if __name__=='__main__':raise SystemExit(main())
