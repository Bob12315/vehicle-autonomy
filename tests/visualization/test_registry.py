from copy import deepcopy
import json,os,tempfile,unittest
from pathlib import Path

from vehicle_autonomy.app.visualization.config import load,frames
from vehicle_autonomy.app.visualization.registry import configure
from vehicle_autonomy.app.visualization.rviz import render
from vehicle_autonomy.app.tools.builtins import registry
from vehicle_autonomy.app.tools.schema import manifest
from vehicle_autonomy.app.tools.workspaces import template
from tests.tool_agent.helpers import CTX


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.token=self.root/'visualization.private';self.token.write_text('fixture-only-'+'x'*40);self.token.chmod(0o600)
        self.config=self.root/'source.json';self.value=dict(schema=1,url='http://127.0.0.1:8780',token_file=str(self.token));self.config.write_text(json.dumps(self.value))
    def test_three_real_topic_profiles_and_safe_goal_tool_are_generated_without_ros_imports(self):
        value=configure(registry(ros_env={}),self.config,{})
        for tool in value['tools']:manifest(tool)
        rviz=next(t for t in value['tools'] if t['id']=='rviz2');bridge=next(t for t in value['tools'] if t['id']=='visualization-bridge')
        for kind in ('rover','copter','plane'):
            self.assertIn(kind,rviz['profiles']);self.assertIn(kind,bridge['profiles'])
            text,names=render(CTX|dict(vehicle_id=kind,vehicle_type=kind,ros_namespace='/'+kind),load(self.config))
            self.assertIn(kind+'/viz/odom',text);self.assertNotIn('__',text);self.assertNotIn('nav2_rviz_plugins',text);self.assertNotIn('SetInitialPose',text)
            self.assertEqual('SetGoal' in text,kind!='plane');self.assertNotIn('Value: /goal_pose',text)
            self.assertEqual(names['tf'],'/'+kind+'/viz/tf')
        public=json.dumps(value);self.assertNotIn(self.token.read_text(),public)
    def test_external_layers_require_explicit_origin_binding_and_have_no_new_tf_owner(self):
        v=self.value|dict(external=dict(origin_id='explicit-source-epoch',fixed_frame='map',odom_frame='odom',base_frame='base_link',tf_topic='/tf',tf_static_topic='/tf_static',topics=dict(points='/rs16/points',map='/slam/map',global_path='/nav2/plan')))
        self.config.write_text(json.dumps(v));config=load(self.config);text,names=render(CTX,config)
        self.assertEqual(names['tf'],'/tf');self.assertIn('Value: /rs16/points',text);self.assertIn('Value: /nav2/plan',text)
        self.config.write_text(json.dumps(v|dict(external=v['external']|dict(odom_frame='odom\nunsafe'))))
        with self.assertRaises(ValueError):load(self.config)
    def test_plain_remote_url_public_credential_and_malformed_origin_are_rejected(self):
        for url in ('http://remote.invalid','http://key@localhost:8780','http://127.0.0.1:8780/?key=x'):
            self.config.write_text(json.dumps(self.value|dict(url=url)))
            with self.assertRaises(ValueError):load(self.config)
        self.config.write_text(json.dumps(self.value));self.token.chmod(0o644)
        with self.assertRaises(ValueError):load(self.config)
    def test_workspace_presets_keep_simulation_ownership_outside_visualization(self):
        value=configure(registry(ros_env={}),self.config,{},owned_simulation=self.root/'manifest.json')
        agents=[dict(id='desktop',role='desktop',tools=[dict(manifest=t) for t in value['tools']])]
        r=template('rover-navigation',CTX,agents);self.assertIn('visualization-bridge',[c['tool_id'] for c in r['components']]);self.assertTrue(next(c for c in r['components'] if c['tool_id']=='nav2')['optional'])
        for kind in ('copter','plane'):
            r=template('uav-visualization',CTX|dict(vehicle_type=kind),agents);self.assertFalse(any(c['tool_id']=='nav2' for c in r['components']))
        r=template('simulation-visualization',CTX,agents);self.assertEqual([c['tool_id'] for c in r['components']],['gazebo','sitl','visualization-bridge','rviz2'])
        for tool in value['tools']:
            if tool['id'] in ('gazebo','sitl'):self.assertIn('simulation',str(tool['profiles']['framework-owned']['argv']));self.assertNotIn('--allow-send',tool['profiles']['framework-owned']['argv'])
