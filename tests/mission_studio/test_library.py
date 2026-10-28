from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from tests.mission_graph import test_graph as legacy
from tests.mission_studio.test_compiler import definition
from vehicle_autonomy.engine.mission.graph import validate
from vehicle_autonomy.app.mission_designer.studio_library import StudioLibrary,RevisionConflict,graph_diff


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'studio';self.store=StudioLibrary(self.path);self.addCleanup(lambda:self.store.close())
    def test_cas_conflict_does_not_replace_other_editor(self):
        first=self.store.save(definition(),0);second=deepcopy(first['definition']);second['name']='Other editor'
        self.store.save(second,1)
        with self.assertRaises(RevisionConflict) as caught:self.store.save(first['definition'],1)
        self.assertEqual(caught.exception.details['current']['definition']['name'],'Other editor')
        self.store.close();self.store=StudioLibrary(self.path)
        self.assertEqual(self.store.snapshot()['drafts']['studio']['definition']['revision'],2)
    def test_missing_established_state_and_concurrent_owner_are_rejected(self):
        with self.assertRaises(BlockingIOError):StudioLibrary(self.path)
        self.store.close();(self.path/'library.json').unlink()
        with self.assertRaises(FileNotFoundError):StudioLibrary(self.path)
    def test_publications_immutable_and_original_runs_not_template_data(self):
        h=legacy.GraphTests();h.setUp();self.addCleanup(h.doCleanups)
        d=self.store.save(definition(),0)['definition'];compiled=validate(d,h.registry,{'v':h.driver})
        pub=self.store.publish('studio',1,compiled)
        d['nodes'][1]['parameters']={'count':2};d=self.store.save(d,1)['definition']
        with self.assertRaises(ValueError):self.store.publish('studio',2,validate(d,h.registry,{'v':h.driver}))
        self.assertEqual(pub['definition_hash'],self.store.snapshot()['publications']['studio@1.0.0']['definition_hash'])
        template=self.store.template('copy',d);self.assertNotIn('runs',template)
        with self.assertRaises(ValueError):self.store.template('copy',d)
        self.assertTrue(graph_diff(pub['definition'],d)['changes'])
