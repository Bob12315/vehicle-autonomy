"""Register a persistent map-coordinate anchor in an idle local Application."""
import argparse
import json
from pathlib import Path
from app.control import request


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--control-socket',required=True)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    try:r=request(a.control_socket,'anchor',{'path':str(a.output.resolve())})
    except (OSError,ValueError,RuntimeError) as exc:r={'ok':False,'error':str(exc)}
    print(json.dumps(r));return 0 if r['ok'] else 1


if __name__=='__main__':raise SystemExit(main())
