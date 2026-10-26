import unittest
from dataclasses import replace
from vehicle_autonomy.contracts.algorithms import AlgorithmProvider
from vehicle_autonomy.contracts.action import ActionResource,ActionSafety
from vehicle_autonomy.engine.providers.catalog import AlgorithmCatalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog=AlgorithmCatalog()
        self.native=AlgorithmProvider('ardupilot_native','navigation','existing-typed-actions','1.0.0',
            frozenset({'rover','copter','plane'}),frozenset({'native_goal'}),frozenset({'signed_ap_state'}),
            frozenset({'native_result'}),'typed_action','owned_simulation',(ActionResource('vehicle.motion'),))
        self.catalog.register(self.native)
    def select(self,**kw):
        args=dict(vehicle_kind='rover',capability='native_goal',assess_idle=lambda:ActionSafety(True),assess_ready=lambda d:True)
        args.update(kw);return self.catalog.select('rover',self.native.provider_id,**args)
    def test_native_capabilities_do_not_claim_nav2_avoidance(self):
        self.assertEqual(self.select(),self.native)
        with self.assertRaises(ValueError):self.select(capability='dynamic_obstacle_avoidance')
        with self.assertRaises(ValueError):self.catalog.register(self.native)
    def test_no_provider_switch_during_unknown_or_continuation(self):
        self.select()
        for value in (ActionSafety(False),ActionSafety(False,True),True):
            with self.assertRaises(ValueError):self.select(assess_idle=lambda:value)
        self.assertEqual(self.catalog.selected('rover','navigation')[0],self.native)
    def test_missing_or_degraded_inputs_and_unsupported_vehicle_rejected(self):
        with self.assertRaises(ValueError):self.select(assess_ready=lambda d:False)
        with self.assertRaises(ValueError):self.select(vehicle_kind='external')
        self.assertIsNone(self.catalog.selected('rover','navigation'))
    def test_bridge_metadata_never_substitutes_security_identity(self):
        nav=replace(self.native,provider_id='nav2',requires_motion_bridge=True)
        self.catalog.register(nav)
        with self.assertRaises(ValueError):self.catalog.select('rover','nav2',vehicle_kind='rover',capability='native_goal',assess_idle=lambda:ActionSafety(True),assess_ready=lambda d:True)
        self.assertIsNone(self.catalog.selected('rover','navigation'))
