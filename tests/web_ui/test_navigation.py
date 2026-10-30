"""Real HTTP navigation capability checks; no vehicle control is granted."""
from types import SimpleNamespace
from threading import Event
import unittest

from vehicle_autonomy.app.tools.service import ToolService
from .helpers import Harness


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.close)
        self.client = self.h.client()
        self.client.login()

    def navigation(self):
        code, body, _ = self.client.call('/api/ui/navigation')
        self.assertEqual(code, 200)
        return body['result']

    def test_navigation_requires_login_and_never_acquires_control(self):
        self.assertEqual(self.h.client().call('/api/ui/navigation')[0], 401)
        view = self.navigation()
        self.assertFalse(view['local'])
        self.assertFalse(view['remote'])
        self.assertEqual([i['id'] for i in view['items']],
                         ['dashboard', 'simulation', 'control', 'studio'])
        self.assertEqual([i['id'] for i in view['advanced']], ['actions'])
        self.assertFalse(self.h.lab.operator_controls.records)
        self.assertFalse(self.h.drivers['rover'].writes)

    def test_local_console_hides_unused_remote_pages_even_with_empty_tool_service(self):
        self.h.lab.control_center = SimpleNamespace(stop=Event())
        tools = ToolService(self.h.directory/'tools')
        self.addCleanup(tools.close)
        self.h.lab.tool_service = tools
        view = self.navigation()
        self.assertTrue(view['local'])
        self.assertFalse(view['remote'])
        self.assertEqual(view['items'][-1]['href'], '/center')
        self.assertEqual(view['items'][-1]['label'], '工具与系统')
        self.assertNotIn('/studio/legacy', str(view))

    def test_configured_remote_host_is_visible_before_connection_and_after_disconnect(self):
        tools = ToolService(self.h.directory/'tools')
        self.addCleanup(tools.close)
        self.h.lab.tool_service = tools
        tools.remote_enabled = True
        view = self.navigation()
        self.assertTrue(view['remote'])
        self.assertEqual([i['id'] for i in view['advanced']],
                         ['actions', 'tools', 'workspaces', 'logs', 'settings'])
        tools.remote_enabled = False
        # A registered but disconnected host must retain its diagnostic menus.
        with tools.registry.lock:
            tools.registry.agents['offline'] = {'connected': False}
        self.assertTrue(self.navigation()['remote'])

    def test_every_advertised_page_and_asset_exists(self):
        self.h.lab.control_center = SimpleNamespace(stop=Event())
        tools = ToolService(self.h.directory/'tools')
        self.addCleanup(tools.close)
        tools.remote_enabled = True
        self.h.lab.tool_service = tools
        view = self.navigation()
        for item in view['items'] + view['advanced']:
            code, body, _ = self.client.call(item['href'].split('#')[0])
            self.assertEqual(code, 200, item)
            self.assertIn(b'data-navigation', body)
            self.assertIn(b'/navigation.js', body)
        for path in ('/navigation.js', '/tool-console.css'):
            self.assertEqual(self.client.call(path)[0], 200)
