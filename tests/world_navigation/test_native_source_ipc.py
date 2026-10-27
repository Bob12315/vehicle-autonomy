import os,socket,time,unittest
from pathlib import Path
from uuid import uuid4
from vehicle_autonomy.world.navigation.source_ipc import NativeSourceSocket,WIRE

class NativeSourceIpcTests(unittest.TestCase):
    def setUp(self):
        self.name='@vaf-native-unit-'+uuid4().hex
        self.ticks=Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')',1)[1].split()[19]
        self.receiver=NativeSourceSocket(self.name,os.getpid(),self.ticks);self.sender=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
    def tearDown(self):self.receiver.close();self.sender.close()
    def frame(self,**kw):
        values=dict(magic=b'VAFNV01\0',channel=0,size=16,reserved=0,source=100,received=time.monotonic_ns()-100_000_000,gid=b'a'*16+b'\0'*8)
        values.update(kw)
        return WIRE.pack(values['magic'],values['channel'],values['size'],values['reserved'],values['source'],values['received'],.1,0.,0.,0.,0.,.2,values['gid'],b'base_link')
    def send(self,data):self.sender.sendto(data,'\0'+self.name[1:])
    def test_real_kernel_credentials_and_original_source_time_survive_transport(self):
        received=time.monotonic_ns()-100_000_000;self.send(self.frame(received=received));values=self.receiver.drain()
        self.assertEqual(len(values),1);frame=values[0]
        self.assertEqual(frame.gid,b'a'*16);self.assertEqual(frame.received_ns,received);self.assertEqual(frame.source_ns,100);self.assertEqual(frame.frame_id,'base_link')
    def test_wrong_process_epoch_malformed_and_missing_gid_never_pass(self):
        self.receiver.start_ticks='1';self.send(self.frame());self.assertEqual(self.receiver.drain(),[])
        self.receiver.start_ticks=self.ticks
        for raw in (self.frame(gid=b'\0'*24),self.frame(magic=b'wrong123'),self.frame()+b'extra'):
            self.send(raw);self.assertEqual(self.receiver.drain(),[])
        self.assertEqual(self.receiver.accepted,0);self.assertEqual(self.receiver.rejected,4)
    def test_drain_budget_is_bounded(self):
        # Nonblocking sender may fill the kernel queue; neither side waits.
        self.sender.setblocking(False);sent=0
        for _ in range(40):
            try:self.send(self.frame());sent+=1
            except BlockingIOError:break
        self.assertLessEqual(len(self.receiver.drain()),32);self.assertGreater(sent,0)
