"""Presentation metadata must never alter a registered execution contract."""
from copy import deepcopy
from pathlib import Path
import unittest

from tests.web_ui.helpers import Harness
from tests.action_system.test_runtime import Factory,Parameters
from vehicle_autonomy.contracts.decision import ActionSpec
from vehicle_autonomy.contracts.action import ActionContext
from vehicle_autonomy.app.mission_designer.action_catalog_report import audit_registry,generate
from vehicle_autonomy.app.mission_designer.action_localization import ACTION_TEXT,CATEGORIES,PARAMETERS,catalog_entry


class CatalogTests(unittest.TestCase):
    def test_source_inventory_has_one_primary_category_and_complete_parameter_labels(self):
        registry=audit_registry();items=registry.catalog()
        self.assertEqual({a['name'] for a in items},set(ACTION_TEXT))
        self.assertEqual(len(items),len({(a['name'],a['version']) for a in items}))
        def fields(schema):
            for key,child in schema.get('properties',{}).items():
                yield key;yield from fields(child)
            for child in schema.get('anyOf',[])+schema.get('prefixItems',[]):yield from fields(child)
            if 'items'in schema:yield from fields(schema['items'])
        for original in items:
            before=deepcopy(original);item=catalog_entry(registry,original);p=item.pop('presentation')
            self.assertEqual(original,before);self.assertEqual(item,before)
            self.assertIn(p['category'],CATEGORIES)
            self.assertNotIn(p['category'],('logic','submission','uncategorized'))
            self.assertNotEqual(p['display_name']['zh-CN'],original['name'])
            for key in fields(original['parameters']):
                self.assertIn(key,p['parameters'],(original['name'],key))
                self.assertTrue(p['parameters'][key]['description']['zh-CN'])
                self.assertIn(key,PARAMETERS)

    def test_unknown_and_factory_metadata_extensions_preserve_identity_and_fallback(self):
        registry=audit_registry();factory=Factory()
        registry.register_typed(ActionSpec('new.custom',Parameters,external_lifecycle='typed_only'),factory)
        original=registry.metadata('new.custom');p=catalog_entry(registry,original)['presentation']
        self.assertEqual(p['category'],'uncategorized');self.assertEqual(p['display_name']['zh-CN'],'new.custom')
        self.assertTrue(p['classification_reason'])
        factory.ui_metadata=dict(category='data',display_name={'zh-CN':'新增数据处理','en-US':'New computation'},required_capabilities=['untrusted'])
        translated=catalog_entry(registry,original)
        self.assertEqual(translated['presentation']['category'],'data')
        self.assertIsNone(translated['presentation']['classification_reason'])
        self.assertEqual(translated['required_capabilities'],original['required_capabilities'])
        self.assertEqual(registry.metadata('new.custom'),original)

    def test_type_capability_provider_and_simulation_availability_are_separate(self):
        h=Harness(kinds=('rover','copter','plane'),standard=True);self.addCleanup(h.close)
        from vehicle_autonomy.actions.navigation.native_rover import register_native_navigation,NativeRoverNavigationFactory
        from vehicle_autonomy.actions.simulation.studio_demo import register_demo
        register_native_navigation(h.lab.registry,object.__new__(NativeRoverNavigationFactory));register_demo(h.lab.registry)
        catalog=h.lab.studio.catalog()
        for target in catalog['library_sets']:
            values=catalog['library_sets'][target]
            self.assertEqual(len(values),len({(a['name'],a['version']) for a in values}))
        def action(target,name):return next(a for a in catalog['library_sets'][target] if a['name']==name)
        self.assertTrue(action('rover','Drive')['availability']['configurable'])
        self.assertFalse(action('rover','Takeoff')['availability']['configurable'])
        self.assertFalse(action('copter','Drive')['availability']['configurable'])
        self.assertTrue(action('plane','SetGuidedTarget')['availability']['configurable'])
        self.assertFalse(action('rover','NavigateToPose')['availability']['configurable'])
        self.assertIn('未绑定',action('rover','NavigateToPose')['availability']['reasons'][0]['zh-CN'])
        h.drivers['copter'].context=lambda: ActionContext('copter','copter',frozenset(),False)
        unowned=next(a for a in h.lab.studio.catalog()['library_sets']['copter'] if a['name']=='Sim.ObserveArea')
        self.assertFalse(unowned['availability']['configurable'])
        self.assertIn('仿真',unowned['availability']['reasons'][0]['zh-CN'])
        self.assertFalse(any(d.writes for d in h.drivers.values()))

    def test_vehicle_specific_bounds_do_not_mutate_registry_schema(self):
        h=Harness(kinds=('copter','plane'),standard=True);self.addCleanup(h.close)
        original=h.lab.registry.metadata('Takeoff')
        catalog=h.lab.studio.catalog()
        copter=next(a for a in catalog['library_sets']['copter'] if a['name']=='Takeoff')
        plane=next(a for a in catalog['library_sets']['plane'] if a['name']=='Takeoff')
        self.assertEqual(copter['parameters']['properties']['height_m']['maximum'],2)
        self.assertEqual(plane['parameters']['properties']['height_m']['const'],50)
        self.assertEqual(h.lab.registry.metadata('Takeoff'),original)

    def test_generated_inventory_is_reproducible_and_uses_real_output_schemas(self):
        self.assertEqual(Path('docs/MISSION_ACTION_CATALOG_ZH_CN.md').read_text(),generate())
        registry=audit_registry()
        self.assertIsNone(registry.metadata('basic.arm')['output'])
        self.assertIn('selected_targets',registry.metadata('Sim.SelectTargets')['output']['properties'])


if __name__=='__main__':unittest.main()
