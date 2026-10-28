import base64,json,os,socket,struct,time,unittest
from urllib.request import Request,urlopen
from .helpers import Harness

class AuthTests(unittest.TestCase):
 def setUp(self):self.h=Harness();self.addCleanup(self.h.close);self.c=self.h.client()
 def test_login_cookie_is_opaque_httponly_and_shared_by_all_pages(self):
  headers=self.c.login();cookie=headers['Set-Cookie']
  self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie);self.assertIn('Path=/',cookie);self.assertNotIn(self.h.token,cookie)
  for route in ('/console','/control','/studio','/','/api/console/state','/api/control/state','/api/studio/state'):
   self.assertEqual(self.c.call(route)[0],200,route)
  self.assertEqual(self.c.call('/api/auth/session')[1]['result']['csrf'],self.c.csrf)
  self.assertEqual(self.h.drivers['rover'].writes,[])
 def test_unauthenticated_api_and_bad_login_rejected_without_credential_leak(self):
  self.assertEqual(self.c.call('/api/control/state')[0],401)
  self.assertEqual(self.c.call('/api/auth/login',{'key':'x'*40})[0],401)
  self.assertEqual(self.c.call('/api/auth/login',{'key':self.h.token},headers={'Origin':'http://evil.invalid'})[0],403)
  self.assertEqual(self.c.call('/api/auth/login',{'key':self.h.token},headers={'Host':'evil.invalid'})[0],403)
  self.assertNotIn(self.h.token,(self.h.directory/'http.jsonl').read_text())
 def test_csrf_origin_expiry_and_logout(self):
  self.c.login()
  self.assertEqual(self.c.call('/api/control/acquire',{'target':'rover'},headers={'X-VAF-CSRF':''})[0],403)
  self.assertEqual(self.c.call('/api/control/acquire',{'target':'rover'},headers={'Origin':'http://evil.invalid'})[0],403)
  self.c.acquire();self.assertEqual(self.c.call('/api/auth/logout',{})[0],200)
  self.assertEqual(self.c.call('/api/control/state')[0],401)
  time.sleep(.1);self.assertNotIn('rover',self.h.lab.operator_controls.records)
  self.c.login();self.h.server.sessions.lifetime_s=.01;time.sleep(.02)
  self.assertEqual(self.c.call('/api/auth/session')[0],401)
 def test_session_expiration_revokes_browser_control_without_new_commands(self):
  self.c.login();self.c.acquire();self.h.server.sessions.idle_s=.01;time.sleep(.15)
  self.assertNotIn('rover',self.h.lab.operator_controls.records);self.assertEqual(self.h.drivers['rover'].writes,[])
 def test_no_page_contains_key_inputs_and_no_long_key_in_storage_code(self):
  self.c.login()
  for route in ('/console','/control','/studio','/'):
   body=self.c.call(route)[1].decode();self.assertNotIn('id="token"',body);self.assertNotIn(self.h.token,body)
  for route in ('/auth.js','/manual-control.js','/tool-console.js','/mission-api.js'):
   body=self.c.call(route)[1].decode();self.assertNotIn('localStorage',body);self.assertNotIn('sessionStorage',body);self.assertNotIn('Bearer ',body)
 def test_reauthentication_rotates_and_revokes_the_previous_session(self):
  self.c.login();old=[c.value for c in self.c.cookies][0];self.c.acquire();self.c.login();new=[c.value for c in self.c.cookies][0]
  self.assertNotEqual(old,new);self.assertIsNone(self.h.server.sessions.lookup(old));self.assertEqual(self.c.call('/api/control/state')[0],200)
 def test_master_bearer_api_remains_authenticated_and_csrf_protected(self):
  hdr={'Authorization':'Bearer '+self.h.token}
  self.assertEqual(self.c.call('/api/control/state',headers=hdr)[0],200)
  self.assertEqual(self.c.call('/api/manual/action',{'name':'ok','target':'rover'},headers=hdr)[0],403)
 def test_request_id_is_scoped_to_browser_principal(self):
  self.c.login();second=self.h.client();second.login()
  first=self.c.call('/api/control/request-takeover',{'target':'rover','confirmed':True},identifier='same')
  other=second.call('/api/control/request-takeover',{'target':'rover','confirmed':False},identifier='same')
  self.assertEqual(first[0],200);self.assertEqual(other[0],409)
 def test_explicit_https_origin_sets_secure_cookie_without_trusting_forwarded_headers(self):
  self.h.server.browser_origin='https://operator.example';self.h.server.secure_cookies=True
  code,data,headers=self.c.call('/api/auth/login',{'key':self.h.token},headers={'Origin':'https://operator.example'})
  self.assertEqual(code,200);self.assertIn('; Secure',headers['Set-Cookie'])
  self.h.server.browser_origin=None;self.h.server.secure_cookies=False
  self.assertEqual(self.c.call('/api/auth/login',{'key':self.h.token},headers={'Origin':'https://operator.example','X-Forwarded-Proto':'https'})[0],403)
 def test_full_session_store_returns_bounded_error_without_issuing_cookie(self):
  for _ in range(128):self.h.server.sessions.create()
  code,data,headers=self.c.call('/api/auth/login',{'key':self.h.token})
  self.assertEqual(code,429);self.assertNotIn('Set-Cookie',headers);self.assertNotIn(self.h.token,str(data))
 def test_session_expiring_during_request_body_cannot_start_an_operation(self):
  from http.client import HTTPConnection
  from unittest.mock import patch
  self.c.login();self.h.server.sessions.lifetime_s=.15
  cookie=next(iter(self.c.cookies));payload=b'{}'
  connection=HTTPConnection('127.0.0.1',self.h.server.server_address[1],timeout=3)
  self.addCleanup(connection.close)
  with patch.object(self.h.lab,'handle',side_effect=AssertionError('expired request reached business operation')) as handle:
   connection.putrequest('POST','/api/missions/start')
   for k,v in {'Cookie':cookie.name+'='+cookie.value,'Origin':self.h.base,'Content-Type':'application/json','Content-Length':str(len(payload)),'X-VAF-CSRF':self.c.csrf,'X-VAF-Request-ID':'delayed-expired-request'}.items():connection.putheader(k,v)
   connection.endheaders();time.sleep(.3);connection.send(payload)
   response=connection.getresponse();data=json.loads(response.read())
   self.assertIn(response.status,(401,409));self.assertFalse(data['ok']);handle.assert_not_called()
  self.assertFalse(self.h.lab.runtime.views());self.assertFalse(self.h.drivers['rover'].writes)
