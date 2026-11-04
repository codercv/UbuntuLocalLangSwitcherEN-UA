from collections import deque
import os
from types import SimpleNamespace
import threading
import unittest

from en_ua.desktop import GnomeLayoutSwitcher, KeyboardGrabTracker


class FakeWindow:
    id = 10

    def __init__(self):
        self.mask = 8
        self.masks = []

    def get_attributes(self):
        return SimpleNamespace(your_event_mask=self.mask)

    def change_attributes(self, event_mask):
        self.mask = event_mask
        self.masks.append(event_mask)


class FakeControl:
    def __init__(self):
        self.window = FakeWindow()
        self.events = deque()
        self.injected = []
        self.keys = {0x20: 65, 0xffeb: 133}
        self.down = False
        self.monitor = None

    def create_resource_object(self, kind, focus):
        assert kind == 'window' and focus == self.window.id
        return self.window

    def sync(self):
        pass

    def flush(self):
        pass

    def pending_events(self):
        return len(self.events)

    def next_event(self):
        return self.events.popleft()

    def keysym_to_keycode(self, symbol):
        return self.keys.get(symbol, 0)

    def query_keymap(self):
        return [int(self.down)]

    def xtest_fake_input(self, event_type, code, time):
        # The real RECORD callback must see signatures queued before input.
        assert self.monitor.synthetic.popleft() == (event_type, code)
        self.injected.append((event_type, code))

    def focus_event(self, event_type, mode):
        self.events.append(SimpleNamespace(type=event_type, mode=mode, window=self.window))


class FakeKeyboard:
    def __init__(self):
        self.group = 0
        self.target = 1

    def group_for(self, language):
        assert language == 'uk'
        return self.target

    def state(self):
        return SimpleNamespace(group=self.group)


class FakeMonitor:
    def __init__(self):
        self.control = FakeControl()
        self.control.monitor = self
        self.keyboard = FakeKeyboard()
        self.synthetic = deque()
        self.stopping = threading.Event()
        self.input_serial = 7
        self.last_skip = ''
        self.focus_id = 10
        self.settle_calls = 0
        self.on_settle = self.activate

    def focus(self):
        return self.focus_id, 'editor'

    def allowed(self, app):
        return app == 'editor'

    def activate(self, ready):
        self.keyboard.group = 1
        return ready()

    def _settle_group(self, group, serial, *, ready, timeout):
        assert group is None and serial == 7 and timeout == 1.0
        self.settle_calls += 1
        return self.on_settle(ready)


class KeyboardGrabTrackerTests(unittest.TestCase):
    def test_tracks_both_popup_and_engine_grabs_and_restores_mask(self):
        control = FakeControl()
        with KeyboardGrabTracker(control, 10) as ready:
            self.assertEqual(control.window.mask, 8 | (1 << 21))
            control.focus_event(10, 1)
            self.assertFalse(ready())
            # Popup ungrab followed by the async engine activation grab.
            control.focus_event(9, 2)
            control.focus_event(10, 1)
            self.assertFalse(ready())
            control.focus_event(9, 2)
            self.assertTrue(ready())
        self.assertEqual(control.window.mask, 8)

    def test_restores_event_mask_after_failure(self):
        control = FakeControl()
        with self.assertRaises(RuntimeError):
            with KeyboardGrabTracker(control, 10):
                raise RuntimeError('cancelled')
        self.assertEqual(control.window.mask, 8)

    def test_grab_state_uses_mode_for_either_focus_direction(self):
        control = FakeControl()
        with KeyboardGrabTracker(control, 10) as ready:
            for event_type in (9, 10):
                control.focus_event(event_type, 1)  # NotifyGrab
                self.assertFalse(ready())
                control.focus_event(event_type, 2)  # NotifyUngrab
                self.assertTrue(ready())

    def test_normal_and_while_grabbed_focus_events_report_current_state(self):
        control = FakeControl()
        with KeyboardGrabTracker(control, 10) as ready:
            for event_type in (9, 10):
                control.focus_event(event_type, 3)  # NotifyWhileGrabbed
                self.assertFalse(ready())
                control.focus_event(event_type, 0)  # NotifyNormal
                self.assertTrue(ready())


class GnomeLayoutSwitcherTests(unittest.TestCase):
    def setUp(self):
        self.monitor = FakeMonitor()
        self.switcher = GnomeLayoutSwitcher(0x20, (0xffeb,), 2)

    def switch(self):
        return self.switcher.switch(self.monitor, 'uk', 7, 10)

    def test_uses_native_shortcut_and_waits_for_engine_ungrab(self):
        def activate(ready):
            self.monitor.keyboard.group = 1
            self.monitor.control.focus_event(10, 1)
            self.assertFalse(ready())
            self.monitor.control.focus_event(9, 2)
            return ready()
        self.monitor.on_settle = activate
        self.assertEqual(self.switch(), 1)
        self.assertEqual(self.monitor.control.injected,
                         [(2, 133), (2, 65), (3, 65), (3, 133)])
        self.assertEqual(self.monitor.control.window.mask, 8)


    def test_rechecks_language_group_after_source_changes_keymap(self):
        def activate(ready):
            self.monitor.keyboard.group = 0
            self.monitor.keyboard.target = 0
            return ready()
        self.monitor.on_settle = activate
        self.assertEqual(self.switch(), 0)

    def test_no_shortcut_when_language_already_active(self):
        self.monitor.keyboard.group = 1
        self.assertEqual(self.switch(), 1)
        self.assertEqual(self.monitor.control.injected, [])
        self.assertEqual(self.monitor.control.window.masks, [])

    def test_unmapped_binding_can_use_next_configured_alternative(self):
        self.switcher = GnomeLayoutSwitcher(0x1234, (0xffeb,), 2,
                                            alternatives=[(0x20, (0xffeb,))])
        self.assertEqual(self.switch(), 1)

    def test_missing_binding_skips_without_input(self):
        self.switcher = GnomeLayoutSwitcher(None)
        self.assertIsNone(self.switch())
        self.assertIn('No usable GNOME', self.monitor.last_skip)
        self.assertEqual(self.monitor.control.injected, [])

    def test_held_keys_or_changed_focus_skip_without_input(self):
        for focus, held in ((20, False), (10, True)):
            self.monitor.focus_id = focus
            self.monitor.control.down = held
            self.assertIsNone(self.switch())
            self.assertEqual(self.monitor.control.injected, [])

    def test_cancelled_settle_preserves_reason_and_restores_mask(self):
        def cancel(ready):
            self.monitor.last_skip = 'new input while switching layout'
            self.monitor.input_serial += 1
            return False
        self.monitor.on_settle = cancel
        self.assertIsNone(self.switch())
        self.assertEqual(self.monitor.last_skip, 'new input while switching layout')
        self.assertEqual(self.monitor.control.window.mask, 8)

    def test_native_source_cycling_is_bounded(self):
        self.monitor.on_settle = lambda ready: ready()
        self.assertIsNone(self.switch())
        self.assertEqual(self.monitor.settle_calls, 2)
        self.assertIn('did not reach', self.monitor.last_skip)
        self.assertEqual(self.monitor.control.window.mask, 8)


@unittest.skipUnless(os.environ.get('EN_UA_X11_TEST') == '1', 'requires an isolated Xvfb display')
class X11KeyboardGrabTrackerTests(unittest.TestCase):
    def test_passively_detects_xinput_keyboard_grab_and_release(self):
        from Xlib import X, display
        from Xlib.ext import xinput

        owner, control, grabber = (display.Display() for _ in range(3))
        for connection in (owner, control, grabber):
            self.addCleanup(connection.close)
        root = owner.screen().root
        window = root.create_window(0, 0, 300, 100, 0, owner.screen().root_depth,
                                    X.InputOutput, X.CopyFromParent)
        self.addCleanup(window.destroy)
        window.map()
        window.set_input_focus(X.RevertToParent, X.CurrentTime)
        owner.sync()
        grab_window = grabber.screen().root.create_window(
            0, 0, 20, 20, 0, grabber.screen().root_depth, X.InputOutput, X.CopyFromParent)
        self.addCleanup(grab_window.destroy)
        grab_window.map()
        grabber.sync()

        with KeyboardGrabTracker(control, window.id) as ready:
            self.assertTrue(ready())
            response = grab_window.xinput_grab_device(
                3, X.CurrentTime, xinput.GrabModeAsync, xinput.GrabModeAsync,
                False, xinput.KeyPressMask | xinput.KeyReleaseMask)
            self.assertEqual(response.status, X.GrabSuccess)
            try:
                control.sync()
                self.assertFalse(ready())
            finally:
                grabber.xinput_ungrab_device(3, X.CurrentTime)
                grabber.sync()
            control.sync()
            self.assertTrue(ready())
        observed_window = control.create_resource_object('window', window.id)
        self.assertEqual(observed_window.get_attributes().your_event_mask, 0)

