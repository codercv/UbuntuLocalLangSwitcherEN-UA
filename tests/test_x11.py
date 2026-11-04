"""Opt-in real X11 application test. Always run inside a fresh Xvfb server."""

import os
import subprocess
import tempfile
import threading
import time
import unittest

from en_ua.config import Config
from tests.helpers import TestDictionaries


@unittest.skipUnless(os.environ.get('EN_UA_X11_TEST') == '1', 'requires an isolated Xvfb display')
class X11KeyboardMappingTests(unittest.TestCase):
    def test_existing_keyboard_refreshes_added_and_reordered_layouts(self):
        from Xlib import display
        from en_ua.x11 import Keyboard

        # Keep a client connected so Xvfb does not reset between setxkbmap
        # and Keyboard opening its independent Xlib connection.
        client = display.Display()
        self.addCleanup(client.close)
        subprocess.run(['setxkbmap', '-layout', 'us'], check=True)
        keyboard = Keyboard()
        self.addCleanup(keyboard.close)
        q_code = keyboard.strokes('q', 0, False)[0][0]
        self.assertEqual(keyboard.group_for('en'), 0)
        self.assertIsNone(keyboard.group_for('uk'))

        subprocess.run(['setxkbmap', '-layout', 'us,ua'], check=True)
        self.assertEqual(keyboard.group_for('uk'), 1)
        self.assertEqual(keyboard.character(q_code, 1 << 13), 'й')

        subprocess.run(['setxkbmap', '-layout', 'ua,us'], check=True)
        self.assertEqual(keyboard.character(q_code, 0), 'й')
        self.assertEqual(keyboard.group_for('uk'), 0)
        self.assertEqual(keyboard.group_for('en'), 1)
        self.assertEqual(keyboard.strokes('q', 1, False), [(q_code, False)])


@unittest.skipUnless(os.environ.get('EN_UA_X11_TEST') == '1', 'requires an isolated Xvfb display')
class X11BackgroundTests(unittest.TestCase):
    def test_normal_x11_client_both_layouts_and_pausing(self):
        from Xlib import display, X
        from en_ua.x11 import Keyboard, X11Monitor

        client = display.Display()
        subprocess.run(['setxkbmap', '-layout', 'us,ua'], check=True)
        keyboard = Keyboard()
        window = client.screen().root.create_window(0, 0, 400, 200, 0, client.screen().root_depth,
                                                    X.InputOutput, X.CopyFromParent,
                                                    event_mask=X.KeyPressMask | X.KeyReleaseMask)
        window.set_wm_class('en-ua-test', 'en-ua-test')
        window.map()
        window.set_input_focus(X.RevertToParent, X.CurrentTime)
        client.sync()
        content = []
        trace = []
        transition = {}

        def drain():
            while client.pending_events():
                event = client.next_event()
                if event.type != X.KeyPress:
                    continue
                symbol = keyboard.symbol(event.detail, (event.state >> 13) & 3)
                trace.append((event.detail, event.state, symbol))
                if symbol == 0xff08:
                    if content:
                        content.pop()
                else:
                    char = keyboard.character(event.detail, event.state)
                    # Model a client whose keymap/IBus group cache lags the
                    # server briefly. The first text key during that interval
                    # is translated using the previous layout (the reported
                    # gривіт failure); later keys use the refreshed layout.
                    event_group = ((event.state >> 13) & 3) or (1 if event.state & 128 else 0)
                    if (char and char.isalpha() and transition and not transition['consumed']
                            and event_group == transition['target']):
                        transition['consumed'] = True
                        if time.monotonic() < transition['ready_at']:
                            previous_state = (event.state & ~(128 | (3 << 13))) | (transition['previous'] << 13)
                            char = keyboard.character(event.detail, previous_state)
                    if char:
                        content.append(char)

        def wait_for(predicate):
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                drain()
                if predicate():
                    return
                time.sleep(0.01)
            self.fail(f'X11 correction timed out, client content={"".join(content)!r}, status={statuses!r}, '
                      f'running={monitor.running}, tracker={monitor.tracker.__dict__}, '
                      f'focus={monitor.focus()}, down={monitor.control.query_keymap()}, skip={monitor.last_skip}, '
                      f'decisions={decisions}, corrections={monitor.corrections}, synthetic={list(monitor.synthetic)}, trace={trace}')

        def type_keys(text):
            for char in text:
                code = client.keysym_to_keycode(ord(char))
                client.xtest_fake_input(X.KeyPress, code)
                client.xtest_fake_input(X.KeyRelease, code)
                client.sync()
                time.sleep(0.015)

        statuses = []
        with tempfile.TemporaryDirectory() as directory:
            config = Config(os.path.join(directory, 'settings.json'))
            monitor = X11Monitor(config, TestDictionaries(), statuses.append)
            decisions = []
            decide = monitor.tracker.decide

            def checked_decide(word, focus):
                result = decide(word, focus)
                decisions.append((word, result))
                return result

            monitor.tracker.decide = checked_decide
            try:
                monitor.start()
                lock_group = monitor.keyboard.lock_group

                def delayed_client_group(group):
                    previous = keyboard.state().group
                    lock_group(group)
                    transition.update(previous=previous, target=group,
                                      ready_at=time.monotonic() + 0.05, consumed=False)

                monitor.keyboard.lock_group = delayed_client_group
                time.sleep(0.1)
                self.assertEqual(keyboard.group_for('en'), 0)
                self.assertEqual(keyboard.group_for('uk'), 1)
                type_keys('ghbdsn ')
                wait_for(lambda: ''.join(content) == 'привіт ' and monitor.corrections == 1)
                self.assertEqual(monitor.corrections, 1)
                self.assertEqual(keyboard.state().group, 1)
                type_keys('hello ')
                wait_for(lambda: ''.join(content) == 'привіт hello ' and monitor.corrections == 2)
                self.assertEqual(monitor.corrections, 2)
                config.data['enabled'] = False
                type_keys('ghbdsn ')
                wait_for(lambda: ''.join(content).endswith('ghbdsn '))
                self.assertEqual(monitor.corrections, 2)
                config.data['enabled'] = True
                window.set_wm_class('gnome-terminal', 'Gnome-terminal')
                client.sync()
                type_keys('ghbdsn ')
                wait_for(lambda: ''.join(content).endswith('ghbdsn ghbdsn '))
                self.assertEqual(monitor.corrections, 2)
                config.data['correct_in_terminals'] = True
                type_keys('ghbdsn ')
                wait_for(lambda: ''.join(content).endswith('ghbdsn ghbdsn привіт ') and monitor.corrections == 3)
                self.assertEqual(monitor.corrections, 3)
                monitor.protected = True
                type_keys('hello ')
                wait_for(lambda: ''.join(content).endswith('руддщ '))
                self.assertEqual(monitor.corrections, 3)
                # New typing during the settling interval must leave the
                # original word intact; RECORD must not be blocked by replay.
                monitor.protected = False
                keyboard.lock_group(0)
                entered, proceed = threading.Event(), threading.Event()
                settle = monitor._settle_group

                def held_settle(group, serial):
                    entered.set()
                    proceed.wait(timeout=1)
                    return settle(group, serial)

                monitor._settle_group = held_settle
                type_keys('ghbdsn ')
                self.assertTrue(entered.wait(timeout=1))
                old_serial = monitor.input_serial
                type_keys('a')
                wait_for(lambda: monitor.input_serial > old_serial)
                untouched = ''.join(content)
                self.assertTrue(untouched.endswith(('ghbdsn a', 'ghbdsn ф')))
                proceed.set()
                wait_for(lambda: not monitor.replay_pending)
                self.assertEqual(''.join(content), untouched)
                self.assertEqual(monitor.corrections, 3)
                self.assertEqual(statuses, [])
            finally:
                monitor.stop()
                keyboard.close()
                window.destroy()
                client.close()


@unittest.skipUnless(os.environ.get('EN_UA_X11_TEST') == '1', 'requires an isolated Xvfb display')
class X11SelectionTests(unittest.TestCase):
    def test_shortcut_converts_selected_text_in_gtk_entry(self):
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, GLib
        from Xlib import X, display
        from en_ua.x11 import X11Monitor

        client = display.Display()
        subprocess.run(['setxkbmap', '-layout', 'us,ua'], check=True)
        window = Gtk.Window()
        window.set_wmclass('selection-test', 'SelectionTest')
        entry = Gtk.Entry()
        entry.set_text('ghbdsn')
        window.add(entry)
        window.show_all()
        window.present()
        entry.grab_focus()
        entry.select_region(0, -1)
        context = GLib.MainContext.default()
        for _ in range(20):
            while context.pending():
                context.iteration(False)
            time.sleep(0.01)
        with tempfile.TemporaryDirectory() as directory:
            monitor = X11Monitor(Config(os.path.join(directory, 'settings.json')), TestDictionaries())
            try:
                monitor.start()
                time.sleep(0.1)
                keys = [client.keysym_to_keycode(key) for key in (0xffe3, 0xffe9, 0x20)]
                for code in keys:
                    client.xtest_fake_input(X.KeyPress, code)
                for code in reversed(keys):
                    client.xtest_fake_input(X.KeyRelease, code)
                client.sync()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline and monitor.corrections == 0:
                    while context.pending():
                        context.iteration(False)
                    time.sleep(0.01)
                self.assertEqual(entry.get_text(), 'привіт', monitor.last_skip)
                self.assertEqual(monitor.corrections, 1, monitor.last_skip)
                monitor.config.data['selection_shortcut'] = 'Ctrl+Shift+F8'
                entry.set_text('руддщ')
                entry.select_region(0, -1)
                while context.pending():
                    context.iteration(False)
                time.sleep(0.1)
                keys = [client.keysym_to_keycode(key) for key in (0xffe3, 0xffe1, 0xffc5)]
                for code in keys:
                    client.xtest_fake_input(X.KeyPress, code)
                for code in reversed(keys):
                    client.xtest_fake_input(X.KeyRelease, code)
                client.sync()
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline and monitor.corrections < 2:
                    while context.pending():
                        context.iteration(False)
                    time.sleep(0.01)
                while context.pending():
                    context.iteration(False)
                self.assertEqual(entry.get_text(), 'hello', monitor.last_skip)
                self.assertEqual(monitor.corrections, 2, monitor.last_skip)
            finally:
                monitor.stop()
                window.destroy()
                client.close()
