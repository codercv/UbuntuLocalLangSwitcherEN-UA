from types import SimpleNamespace
import unittest
from unittest.mock import patch

from en_ua.config import DEFAULTS
from en_ua.x11 import X11Monitor
from tests.helpers import TestDictionaries


class X11PasswordFocusTests(unittest.TestCase):
    def test_password_protection_expires_when_x11_focus_changes(self):
        monitor = X11Monitor(SimpleNamespace(data=dict(DEFAULTS)), TestDictionaries())
        window = SimpleNamespace(id=10, get_wm_class=lambda: ('browser', 'Browser'))
        monitor.control = SimpleNamespace(get_input_focus=lambda: SimpleNamespace(focus=window))
        monitor.protected = True
        monitor.focus()
        self.assertTrue(monitor.protected)
        self.assertFalse(monitor.allowed('browser'))

        window.id = 20
        monitor.focus()
        self.assertFalse(monitor.protected)
        self.assertTrue(monitor.allowed('browser'))

    def test_explicit_unprotect_removes_the_previous_focus(self):
        monitor = X11Monitor(SimpleNamespace(data=dict(DEFAULTS)), TestDictionaries())
        window = SimpleNamespace(id=10, get_wm_class=lambda: ('browser', 'Browser'))
        monitor.control = SimpleNamespace(get_input_focus=lambda: SimpleNamespace(focus=window))
        monitor.protected = True
        monitor.protected = False
        self.assertIsNone(monitor.protected_focus)
        self.assertFalse(monitor.protected)


class LayoutReadinessTests(unittest.TestCase):
    def setUp(self):
        self.monitor = X11Monitor(SimpleNamespace(data=dict(DEFAULTS)), TestDictionaries())
        self.clock = 0
        self.monitor.keyboard = SimpleNamespace(state=lambda: SimpleNamespace(group=1))
        self.monitor.stopping = SimpleNamespace(is_set=lambda: False, wait=self.advance)

    def advance(self, duration):
        self.clock += duration

    def test_stable_group_waits_for_desktop_keyboard_ungrab(self):
        with patch('en_ua.x11.time.monotonic', side_effect=lambda: self.clock):
            self.assertTrue(self.monitor._settle_group(1, 0,
                ready=lambda: self.clock >= 0.2, timeout=0.5))
        self.assertGreaterEqual(self.clock, 0.28)

    def test_stuck_desktop_grab_skips_without_replaying(self):
        with patch('en_ua.x11.time.monotonic', side_effect=lambda: self.clock):
            self.assertFalse(self.monitor._settle_group(1, 0,
                ready=lambda: False, timeout=0.05))
        self.assertEqual(self.monitor.last_skip, 'desktop keyboard grab did not end')

    def test_reverted_group_is_distinct_from_new_input(self):
        self.monitor.keyboard.state = lambda: SimpleNamespace(group=int(self.clock < 0.01))
        with patch('en_ua.x11.time.monotonic', side_effect=lambda: self.clock):
            self.assertFalse(self.monitor._settle_group(1, 0, timeout=0.1))
        self.assertEqual(self.monitor.last_skip, 'keyboard layout did not settle')
