"""Independent physics contact evidence; never supplied to World or control.

Gazebo Harmonic public Contact sensor/system interface:
https://gazebosim.org/docs/harmonic/sensors/
"""
from collections import deque
import json
from pathlib import Path
from threading import RLock
import time
import xml.etree.ElementTree as ET


def attach_contacts(owned):
    tree=ET.parse(owned.model_path);topics=[]
    for link in tree.findall('model/link'):
        collisions=link.findall('collision')
        if not collisions:continue
        topic='/phase5/contacts/'+link.get('name');sensor=ET.SubElement(link,'sensor',name='phase5_contacts',type='contact')
        ET.SubElement(sensor,'always_on').text='true';ET.SubElement(sensor,'update_rate').text='50';ET.SubElement(sensor,'topic').text=topic
        # gz-sim 8.15 Contact reads contact/topic, not sensor/topic.
        contact=ET.SubElement(sensor,'contact');ET.SubElement(contact,'topic').text=topic
        for collision in collisions:ET.SubElement(contact,'collision').text=collision.get('name')
        topics.append(topic)
    tree.write(owned.model_path)
    world=ET.parse(owned.world_path);ET.SubElement(world.find('world'),'plugin',filename='gz-sim-contact-system',name='gz::sim::systems::Contact');world.write(owned.world_path)
    return tuple(topics)


class ContactOracle:
    def __init__(self,topics,directory):
        from gz.transport13 import Node
        from gz.msgs10.contacts_pb2 import Contacts
        self.node=Node();self.topics=topics;self.lock=RLock();self.frames=0;self.ground_pairs=0;self.obstacle_pairs=0;self.unknown_pairs=0;self.recent=deque(maxlen=4096);self.error=None;self.closed=False;self.last_logged={};self.logged_bytes=0;self.suppressed_ground_pairs=0
        self.log=(Path(directory)/'physics-contacts.jsonl').open('x')
        for topic in topics:
            if not self.node.subscribe(Contacts,topic,lambda m,t=topic:self.receive(t,m)):raise RuntimeError('actual contact subscription failed')
    def receive(self,topic,message):
        with self.lock:
            if self.closed:return
            try:
                self.frames+=1
                for contact in message.contact:
                    a=contact.collision1.name;b=contact.collision2.name
                    if not a or not b:self.unknown_pairs+=1
                    elif 'ground_plane' in a or 'ground_plane' in b:self.ground_pairs+=1
                    else:self.obstacle_pairs+=1
                    row=dict(host_ns=time.monotonic_ns(),source_ns=message.header.stamp.sec*1_000_000_000+message.header.stamp.nsec,topic=topic,collision1=a,collision2=b,entity1=contact.collision1.id,entity2=contact.collision2.id,depths=list(contact.depth))
                    self.recent.append(row)
                    ground='ground_plane' in a or 'ground_plane' in b
                    if ground and row['source_ns']-self.last_logged.get(topic,-20_000_000)<20_000_000:
                        self.suppressed_ground_pairs+=1;continue
                    line=json.dumps(row)+'\n'
                    if self.logged_bytes+len(line)>32*1024*1024:raise ValueError('contact evidence byte budget exhausted')
                    self.last_logged[topic]=row['source_ns'];self.logged_bytes+=len(line);self.log.write(line)
                self.log.flush()
            except Exception as exc:self.error=type(exc).__name__
    def snapshot(self):
        with self.lock:return dict(frames=self.frames,ground_pairs=self.ground_pairs,obstacle_pairs=self.obstacle_pairs,unknown_pairs=self.unknown_pairs,error=self.error,logged_bytes=self.logged_bytes,suppressed_ground_pairs=self.suppressed_ground_pairs)
    def close(self):
        with self.lock:self.closed=True
        for topic in self.topics:self.node.unsubscribe(topic)
        with self.lock:self.log.close()
