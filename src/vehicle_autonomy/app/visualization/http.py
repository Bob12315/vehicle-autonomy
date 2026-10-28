"""Narrow visualization capability: state reads and inert proposals only."""
import hmac
import json
from urllib.parse import parse_qs,urlsplit

from vehicle_autonomy.app.tools.schema import identifier
from .state import snapshot


def capability(handler):
    token=getattr(handler.server,'visualization_token',None)
    return bool(token and hmac.compare_digest(handler.headers.get('Authorization','').encode(),('Bearer '+token).encode()))


def get(handler):
    path=urlsplit(handler.path)
    if path.path not in ('/api/visualization/state','/api/visualization/candidates'):return False
    if not handler.trusted_origin():return True
    if not (path.path.endswith('/state') and capability(handler)) and not handler.authorized():return True
    try:
        query=parse_qs(path.query,strict_parsing=True)
        if set(query)!={'target'} or len(query['target'])!=1:raise ValueError('one target required')
        target=identifier(query['target'][0]);service=handler.server.service
        result=snapshot(service,target) if path.path.endswith('/state') else service.visualization_goals.view(target)
        handler.reply(200,dict(ok=True,result=result))
    except (KeyError,ValueError,TypeError):handler.reply(409,dict(ok=False,error='visualization source or target unavailable'))
    return True


def post(handler):
    # Other routes still require the normal operator identity. In particular
    # this capability cannot call /manual, /run, Mission or confirmation APIs.
    if handler.path!='/api/visualization/candidates' or not capability(handler):return False
    if not handler.trusted_origin():return True
    try:
        if handler.headers.get('Transfer-Encoding') or handler.headers.get('Content-Type')!='application/json' or handler.headers.get('X-VAF-Visualization')!='candidate-v1':raise ValueError('explicit candidate request required')
        length=int(handler.headers.get('Content-Length','-1'))
        if not 0<length<=4096:raise ValueError('candidate request budget exceeded')
        result=handler.server.service.visualization_goals.submit(json.loads(handler.rfile.read(length)))
        handler.reply(200,dict(ok=True,result=result))
    except (KeyError,ValueError,TypeError):handler.reply(409,dict(ok=False,error='candidate rejected: check pose, frame, epoch, localization, TTL and rate'))
    return True
