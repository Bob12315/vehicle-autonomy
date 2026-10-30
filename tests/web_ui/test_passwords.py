"""Password-only local-console browser login, storage, and auth boundaries."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from vehicle_autonomy.app.web.passwords import load_password,set_password
from tests.web_ui.helpers import Harness

PASSWORD='testPassword-42'


class PasswordStorageTests(unittest.TestCase):
    def test_salted_private_verifier_roundtrip_and_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'password.json';other=Path(folder)/'other.json'
            set_password(path,PASSWORD);set_password(other,PASSWORD)
            first=path.read_text();self.assertNotIn(PASSWORD,first)
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertNotEqual(json.loads(first)['salt'],json.loads(other.read_text())['salt'])
            self.assertTrue(load_password(path).verify(PASSWORD));self.assertFalse(load_password(path).verify('wrong-password'))
            set_password(path,'new-password');self.assertFalse(load_password(path).verify(PASSWORD))
            self.assertTrue(load_password(path).verify('new-password'))

    def test_unsafe_file_or_hash_parameters_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'password.json';set_password(path,PASSWORD)
            path.chmod(0o644)
            with self.assertRaises(ValueError):load_password(path)
            path.chmod(0o600);link=Path(folder)/'linked.json';link.symlink_to(path)
            with self.assertRaises(OSError):load_password(link)
            with self.assertRaises(OSError):set_password(link,'new-password')
            value=json.loads(path.read_text());value['iterations']=1;path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):load_password(path)

    def test_invalid_password_cannot_replace_existing_verifier(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'password.json';set_password(path,PASSWORD);before=path.read_text()
            for value in ('short','x'*257,None):
                with self.assertRaises(ValueError):set_password(path,value)
            self.assertEqual(path.read_text(),before)


class PasswordWebTests(unittest.TestCase):
    def setUp(self):
        self.h=Harness();self.addCleanup(self.h.close)
        self.path=self.h.directory/'password.json';set_password(self.path,PASSWORD)
        self.h.server.password_auth=load_password(self.path);self.c=self.h.client()

    def login(self,password=PASSWORD):return self.c.call('/api/auth/login',{'password':password})

    def test_password_login_cookie_csrf_and_shared_pages(self):
        self.assertEqual(self.c.call('/api/center/state')[0],401)
        self.assertEqual(self.login('wrong-password')[0],401)
        code,body,headers=self.login();self.assertEqual(code,200)
        self.c.csrf=body['result']['csrf'];self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertEqual(self.c.call('/api/auth/session')[0],200)
        for page in ('/center','/simulation','/control','/studio','/console'):
            self.assertEqual(self.c.call(page)[0],200)
        self.assertEqual(self.c.call('/api/control/acquire',{'target':'rover'},headers={'X-VAF-CSRF':''})[0],403)
        self.assertEqual(self.c.call('/api/auth/logout',{})[0],200)
        self.assertEqual(self.c.call('/api/auth/session')[0],401)
        self.assertNotIn(PASSWORD,(self.h.directory/'http.jsonl').read_text())
        self.assertFalse(any(d.writes for d in self.h.drivers.values()))

    def test_old_login_key_is_not_accepted_as_console_password(self):
        self.assertEqual(self.c.call('/api/auth/login',{'key':self.h.token})[0],400)
        self.assertEqual(self.login(self.h.token)[0],401)
        self.assertEqual(self.c.call('/api/auth/session',headers={'Authorization':'Bearer '+PASSWORD})[0],401)

    def test_same_origin_and_rate_limit_remain_required(self):
        self.assertEqual(self.c.call('/api/auth/login',{'password':PASSWORD},headers={'Origin':'http://evil.invalid'})[0],403)
        for _ in range(10):self.assertEqual(self.login('wrong-password')[0],401)
        self.assertEqual(self.login()[0],429)

    def test_eight_character_password_is_valid_login_input(self):
        set_password(self.path,'24681357');self.h.server.password_auth=load_password(self.path)
        self.assertEqual(self.login('24681357')[0],200)
        code,data,_=self.c.call('/login');self.assertEqual(code,200)
        self.assertIn('登录密码'.encode(),data);self.assertNotIn('访问密钥'.encode(),data)
