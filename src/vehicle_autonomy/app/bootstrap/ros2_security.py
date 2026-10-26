"""Explicit isolated SROS2 provisioning; uses official keystore APIs.

No key contents are inspected, logged or returned. The caller must register the
fresh parent directory with its credential owner BEFORE launching this worker.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import xml.etree.ElementTree as ET


def policy(profiles):
    root=ET.Element('policy',version='0.2.0');enclaves=ET.SubElement(root,'enclaves')
    for role,permissions in profiles.items():
        if not isinstance(role,str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',role):raise ValueError('fixed local role required')
        if type(permissions) is not dict or permissions.keys()-{'topics','services','actions'}:raise ValueError('unknown security interface group')
        for group,directions in (('topics',{'publish','subscribe'}),('services',{'request','reply'}),('actions',{'call','execute'})):
            entries=permissions.get(group,{})
            if type(entries) is not dict or entries.keys()-directions or any(not isinstance(v,(list,tuple)) or len(v)>128 for v in entries.values()):raise ValueError('unknown or unbounded security permission')
        enclave=ET.SubElement(enclaves,'enclave',path='/vaf/'+role);group=ET.SubElement(enclave,'profiles');profile=ET.SubElement(group,'profile',ns='/',node='*')
        for tag,directions,item in (('topics',('publish','subscribe'),'topic'),('services',('request','reply'),'service'),('actions',('call','execute'),'action')):
            for direction in directions:
                values=list(permissions.get(tag,{}).get(direction,()))
                if tag=='topics' and direction=='publish':values+=['/rosout','/parameter_events']
                if tag=='services' and direction=='reply':values+=['/*/get_type_description']
                if not values:continue
                element=ET.SubElement(profile,tag,**{direction:'ALLOW'})
                for value in sorted(set(values)):
                    if not isinstance(value,str) or not value.startswith('/') or len(value)>256:raise ValueError('absolute bounded ROS interface required')
                    ET.SubElement(element,item).text=value
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def create(root,profiles):
    root=Path(root).absolute()
    if root.resolve()!=root or root.exists():raise ValueError('fresh keystore required')
    parent=root.parent;info=parent.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('registered private owned credential parent required')
    from sros2 import keystore
    content=policy(profiles);profile=parent/'policy.xml';profile.write_bytes(content)
    keystore.create_keystore(root)
    for role in profiles:
        enclave='/vaf/'+role;keystore.create_enclave(root,enclave);keystore.create_permission(root,enclave,profile)
    for file in root.rglob('*'):
        if not file.is_symlink() and file.is_file() and (file.name=='key.pem' or file.name.endswith('.key.pem')):file.chmod(0o600)
    return dict(schema=1,domain=int(os.environ.get('ROS_DOMAIN_ID','0')),roles=sorted(profiles),policy_sha256=hashlib.sha256(content).hexdigest(),method='official sros2 keystore/create_enclave/create_permission APIs')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--profiles',type=Path,required=True);p.add_argument('--result',type=Path,required=True);a=p.parse_args()
    data=json.loads(a.profiles.read_text())
    if type(data) is not dict or not 1<=len(data)<=16:raise ValueError('bounded explicit security roles required')
    a.result.write_text(json.dumps(create(a.root,data),indent=2))


if __name__=='__main__':main()
