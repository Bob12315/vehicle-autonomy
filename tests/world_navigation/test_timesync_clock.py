from types import SimpleNamespace
import unittest
from tests.world_navigation.test_streams import stamp
from vehicle_autonomy.vehicles.ardupilot.timesync_clock import TimesyncSourceClock


def message(kind,**kw):return SimpleNamespace(get_type=lambda:kind,**kw)

class TimesyncClockTests(unittest.TestCase):
    def sync(self,clock,host,boot,*,after_bytes=0):
        at=stamp(host);nonce=clock.request_due(at);self.assertIsNotNone(nonce);clock.sent(nonce,at,100)
        return clock.observe(message('TIMESYNC',tc1=boot,ts1=nonce,_vaf_signature_timestamp=1),stamp(host+2_000_000),100+after_bytes)
    def test_signed_nonce_roundtrip_and_uart_correction_bound(self):
        clock=TimesyncSourceClock();self.assertTrue(self.sync(clock,1_000_000_000,1_000_000_000))
        # tc1 is wire-time corrected. Samples below the upper correction bound
        # cannot be promoted to a post-request capture time.
        self.assertIsNone(clock.capture(message('LOCAL_POSITION_NED',time_boot_ms=1001),stamp(1_050_000_000)))
        point=clock.capture(message('LOCAL_POSITION_NED',time_boot_ms=1020),stamp(1_050_000_000))
        self.assertEqual(point,stamp(1_000_000_000))
        self.assertIsNone(clock.capture(message('HEARTBEAT'),stamp(1_050_000_000)))
        self.assertIsNone(clock.capture(message('COMMAND_ACK'),stamp(1_050_000_000)))
    def test_wrong_nonce_unsigned_old_response_and_old_pose_do_not_refresh(self):
        clock=TimesyncSourceClock();at=stamp(1_000_000_000);nonce=clock.request_due(at);clock.sent(nonce,at,0)
        for sig,echo in ((None,nonce),(1,nonce+1)):
            self.assertFalse(clock.observe(message('TIMESYNC',tc1=1_000_000_000,ts1=echo,_vaf_signature_timestamp=sig),stamp(1_002_000_000),0))
        self.assertTrue(clock.observe(message('TIMESYNC',tc1=1_000_000_000,ts1=nonce,_vaf_signature_timestamp=1),stamp(1_002_000_000),0))
        self.assertFalse(clock.observe(message('TIMESYNC',tc1=1_000_000_000,ts1=nonce,_vaf_signature_timestamp=1),stamp(1_003_000_000),0))
        point=clock.capture(message('LOCAL_POSITION_NED',time_boot_ms=1020),stamp(10_000_000_000))
        self.assertEqual(point.monotonic_ns,1_000_000_000)
    def test_variable_simulation_rate_stays_conservative_and_bounded(self):
        clock=TimesyncSourceClock()
        for n in range(1,1001):
            host=n*100_000_000;boot=n*90_000_000
            self.assertTrue(self.sync(clock,host,boot))
            point=clock.capture(message('LOCAL_POSITION_NED',time_boot_ms=(boot+20_000_000)//1_000_000),stamp(host+40_000_000))
            self.assertEqual(point.monotonic_ns,host)
        self.assertEqual(len(clock._anchors),64)
        with self.assertRaises(ValueError):clock.capture(message('LOCAL_POSITION_NED',time_boot_ms=1),stamp(host+50_000_000))
    def test_following_fifo_bytes_increase_source_threshold_not_capture_time(self):
        clock=TimesyncSourceClock();self.assertTrue(self.sync(clock,1_000_000_000,1_000_000_000,after_bytes=200))
        self.assertIsNone(clock.capture(message('ATTITUDE',time_boot_ms=1020),stamp(1_100_000_000)))
        point=clock.capture(message('ATTITUDE',time_boot_ms=1050),stamp(1_100_000_000));self.assertEqual(point.monotonic_ns,1_000_000_000)
