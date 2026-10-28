import base64,json,os,socket,struct,time,unittest
from .helpers import Harness

class Wire:
 def __init__(self,h,c,*,origin=None,path='/ws/telemetry',cookie=True):
  self.sock=socket.create_connection(h.server.server_address,timeout=3);self.buffer=b''
  key=base64.b64encode(os.urandom(16)).decode();host=h.base.split('://')[1]
  headers=[f'GET {path} HTTP/1.1','Host: '+host,'Connection: Upgrade','Upgrade: websocket','Sec-WebSocket-Version: 13','Sec-WebSocket-Key: '+key,'Origin: '+(origin or h.base)]
  if cookie:headers.append('Cookie: '+'; '.join(x.name+'='+x.value for x in c.cookies))
  self.sock.sendall(('\r\n'.join(headers)+'\r\n\r\n').encode())
  while b'\r\n\r\n' not in self.buffer:self.buffer+=self.sock.recv(4096)
  self.headers,self.buffer=self.buffer.split(b'\r\n\r\n',1)
 def read(self,n):
  while len(self.buffer)<n:
   value=self.sock.recv(65536)
   if not value:raise EOFError()
   self.buffer+=value
  result,self.buffer=self.buffer[:n],self.buffer[n:];return result
 def frame(self):
  first,second=self.read(2);size=second&127
  if size==126:size=struct.unpack('!H',self.read(2))[0]
  elif size==127:size=struct.unpack('!Q',self.read(8))[0]
  return first&15,self.read(size)
 def send(self,opcode,payload=b''):
  mask=b'abcd';self.sock.sendall(bytes([128|opcode,128|len(payload)])+mask+bytes(x^mask[i%4] for i,x in enumerate(payload)))
 def close(self):self.sock.close()

class LiveTests(unittest.TestCase):
 def setUp(self):self.h=Harness();self.addCleanup(self.h.close);self.c=self.h.client();self.c.login()
 def wire(self,**kw):w=Wire(self.h,self.c,**kw);self.addCleanup(w.close);return w
 def test_origin_cookie_and_no_url_credentials(self):
  for kw,code in [({'origin':'http://evil.invalid'},403),({'cookie':False},401),({'path':'/ws/telemetry?token=x'},400)]:
   self.assertIn(str(code).encode(),self.wire(**kw).headers)
 def test_authenticated_readonly_frames_ping_and_reconnection(self):
  for _ in range(2):
   w=self.wire();self.assertIn(b'101 Switching Protocols',w.headers)
   opcode,payload=w.frame();self.assertEqual(opcode,1);data=json.loads(payload)
   self.assertEqual(data['type'],'telemetry');self.assertNotIn(self.h.token,payload.decode())
   w.send(9,b'ping')
   while True:
    opcode,payload=w.frame()
    if opcode==10:self.assertEqual(payload,b'ping');break
   w.close()
  self.assertEqual(self.h.drivers['rover'].writes,[])
 def test_client_cannot_send_control_commands_on_websocket(self):
  w=self.wire();w.frame();w.send(1,b'{"action":"Arm"}')
  opcode,payload=w.frame();self.assertEqual(opcode,8);self.assertEqual(struct.unpack('!H',payload[:2])[0],1003)
  self.assertEqual(self.h.lab.runtime.views(),[])
 def test_expiry_and_logout_close_live_connection(self):
  for expired in (True,False):
   self.c.login();w=self.wire();w.frame()
   if expired:self.h.server.sessions.lifetime_s=.01;time.sleep(.03)
   else:self.c.call('/api/auth/logout',{})
   while True:
    opcode,payload=w.frame()
    if opcode==8:self.assertEqual(struct.unpack('!H',payload[:2])[0],4401);break
   w.close();self.h.server.sessions.lifetime_s=28800
