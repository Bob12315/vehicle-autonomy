"""Trusted deployment config; credentials stay off browser/ROS/argv/logs."""
import json
import os
from pathlib import Path
import stat
import re
from urllib.parse import urlsplit

from vehicle_autonomy.app.tools.schema import object_fields,context


def load(path):
    value=json.loads(Path(path).read_text())
    object_fields(value,('schema','url','token_file'),('use_sim_time','external'))
    url=urlsplit(value['url'])
    if value['schema']!=1 or url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:raise ValueError('explicit HTTP(S) backend origin required')
    if url.scheme=='http' and url.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('remote plaintext feed forbidden; use HTTPS or a loopback SSH tunnel')
    if type(value.get('use_sim_time',False)) is not bool:raise ValueError('explicit use_sim_time boolean required')
    token=Path(value['token_file'])
    if not token.is_absolute() or token.is_symlink() or not token.is_file():raise ValueError('existing absolute visualization credential file required')
    info=token.stat()
    if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:raise ValueError('visualization credential must be private and owned')
    if value.get('external') is not None:
        external=value['external'];object_fields(external,('origin_id','fixed_frame','odom_frame','base_frame','tf_topic','tf_static_topic','topics'))
        if type(external['origin_id']) is not str or not 1<=len(external['origin_id'])<=256 or any(c in external['origin_id'] for c in '\n\r\x00'):raise ValueError('explicit calibrated external origin binding required')
        for key in ('fixed_frame','odom_frame','base_frame'):
            if type(external[key]) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_/]{0,127}',external[key]):raise ValueError('qualified external ROS frame required')
        for key in ('tf_topic','tf_static_topic'):
            if type(external[key]) is not str or not re.fullmatch(r'/[A-Za-z_][A-Za-z0-9_/]{0,127}',external[key]):raise ValueError('absolute external TF topic required')
        allowed={'scan','points','map','global_path','local_path','global_costmap','local_costmap','perception'}
        if type(external['topics']) is not dict or set(external['topics'])-allowed or any(type(v) is not str or not v.startswith('/') or not all(c.isalnum() or c in '/_' for c in v) for v in external['topics'].values()):raise ValueError('standard absolute external topic mappings required')
    return value


def vehicle_context():
    result=context(dict(vehicle_id=os.environ['VAF_VEHICLE_ID'],vehicle_type=os.environ['VAF_VEHICLE_TYPE'],
        environment=os.environ['VAF_ENVIRONMENT'],ros_namespace=os.environ['ROS_NAMESPACE'],
        ros_domain_id=int(os.environ['ROS_DOMAIN_ID']),mavlink_profile='visualization'))
    if os.environ.get('VAF_VISUALIZATION_KIND',result['vehicle_type'])!=result['vehicle_type']:raise ValueError('selected visualization profile does not match vehicle type')
    return result


def frames(ctx,config):
    ns=ctx['ros_namespace'].rstrip('/');prefix=(ns or '/vehicle')+'/viz'
    external=config.get('external')
    return dict(namespace=ns,topic=prefix,odom=external['odom_frame'] if external else prefix.lstrip('/')+'/odom',
        base=external['base_frame'] if external else prefix.lstrip('/')+'/base_link',fixed=external['fixed_frame'] if external else prefix.lstrip('/')+'/odom',
        tf=external['tf_topic'] if external else prefix+'/tf',tf_static=external['tf_static_topic'] if external else prefix+'/tf_static')
