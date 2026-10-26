from dataclasses import replace
import unittest
from tests.world_navigation.test_streams import stamp
from vehicle_autonomy.engine.navigation.mailbox import NavigationBinding,NavigationCommand,NavigationMailbox

class NavigationMailboxTests(unittest.TestCase):
    def setUp(self):
        self.binding=NavigationBinding('action','rover','nav2','provider_epoch','session','world','goal','ab'*24,'host')
        self.box=NavigationMailbox(self.binding,stamp(0))
    def command(self,n=0,at=0,v=0.,w=0.):return NavigationCommand(self.binding,n,at,stamp(at),stamp(at+1),v,w)
    def test_normal_bounded_ramp_braking_and_deadman(self):
        self.box.accept(self.command(),stamp(1))
        for n in range(1,101):
            t=n*50_000_000;self.box.accept(self.command(n,t,min(.3,n*.015)),stamp(t+1))
        self.assertAlmostEqual(self.box.latest(stamp(t+100_000_000)).speed_mps,.3)
        self.box.accept(self.command(101,t+50_000_000),stamp(t+50_000_001))
        with self.assertRaises(ValueError):self.box.latest(stamp(t+250_000_000))
        self.assertEqual(self.box.accepted,102)
    def test_old_goal_target_provider_session_generation_source_and_clock_rejected(self):
        self.box.accept(self.command(),stamp(1))
        for key in ('action_id','target_id','provider_id','provider_epoch','vehicle_session','world_generation','goal_id','clock_domain'):
            with self.assertRaises(ValueError):self.box.accept(replace(self.command(1,10),binding=replace(self.binding,**{key:'other'})),stamp(11))
        with self.assertRaises(ValueError):self.box.accept(replace(self.command(1,10),binding=replace(self.binding,producer_gid='cd'*24)),stamp(11))
        self.assertEqual(self.box.accepted,1)
    def test_repeated_receipt_and_reordering_cannot_renew_source(self):
        c=self.command();self.box.accept(c,stamp(1))
        for n in range(1,1000):
            with self.assertRaises(ValueError):self.box.accept(replace(c,sequence=n,received_at=stamp(n+1)),stamp(n+1))
        self.assertEqual(self.box.accepted,1)
        with self.assertRaises(ValueError):self.box.latest(stamp(200_000_000))
    def test_limits_future_acceleration_and_closed_ingress(self):
        with self.assertRaises(ValueError):self.command(0,10,float('nan'))
        with self.assertRaises(ValueError):self.box.accept(self.command(0,10,.5),stamp(11))
        with self.assertRaises(ValueError):self.box.accept(self.command(0,20),stamp(10))
        self.box.accept(self.command(),stamp(1));self.box.close()
        with self.assertRaises(ValueError):self.box.accept(self.command(1,10),stamp(11))
        with self.assertRaises(ValueError):self.box.latest(stamp(11))
