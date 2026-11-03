import time
import unittest
from tests.mission_graph import test_service as legacy
from tests.mission_studio.test_compiler import definition


class StudioServiceTests(unittest.TestCase):
    def setUp(self):
        self.h=legacy.ServiceTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        from tests.web_ui.helpers import FixtureDriver
        self.h.driver.snapshot=FixtureDriver('rover').snapshot
    def api(self,op,p=None,**kw):return self.h.api('/api/studio-b/'+op.replace('.','/'),p,**kw)
    def test_authenticated_draft_publish_run_immutable_snapshot_chain(self):
        self.assertEqual(self.api('library',auth=False)[0],401)
        self.assertEqual(self.api('draft.save',dict(definition=definition(),expected_revision=0),csrf=False)[0],403)
        code,result=self.api('draft.save',dict(definition=definition(),expected_revision=0));self.assertEqual(code,200,result)
        code,result=self.api('draft.validate',dict(mission_id='studio',revision=1));self.assertEqual(code,200,result)
        code,result=self.api('draft.publish',dict(mission_id='studio',revision=1));self.assertEqual(code,200,result)
        publication=result['result'];binding=self.api('catalog')[1]['result']['vehicles'][0]['binding']
        code,result=self.api('run.start',dict(publication='studio@1.0.0',definition_hash=publication['definition_hash'],binding=binding,allow_send=False));self.assertEqual(code,200,result);identifier=result['result']['id']
        d=definition();d['name']='Edited after start';self.api('draft.save',dict(definition=d,expected_revision=1))
        until=time.monotonic()+3
        while time.monotonic()<until:
            code,result=self.api('run.get',dict(id=identifier));self.assertEqual(code,200,result)
            if result['result']['state']=='SUCCEEDED':break
            time.sleep(.05)
        self.assertEqual(result['result']['state'],'SUCCEEDED',result)
        self.assertEqual(result['result']['studio']['definition']['name'],'Studio');self.assertEqual(self.h.driver.writes,[])
        self.assertEqual(self.api('run.debug',dict(id=identifier,operation='resume'))[0],409)
    def test_conflict_response_and_export_copy_do_not_overwrite(self):
        p=dict(definition=definition(),expected_revision=0);self.api('draft.save',p)
        code,result=self.api('draft.save',p);self.assertEqual(code,409);self.assertEqual(result['conflict']['current']['definition']['revision'],1)
        code,result=self.api('draft.clone',dict(source='studio',new_mission_id='copy'));self.assertEqual(code,200,result)
        self.assertEqual(result['result']['definition']['mission_id'],'copy')
        self.assertEqual(len(self.api('library')[1]['result']['drafts']),2)
