"""Passive X11 RECORD observer and narrowly scoped XTEST replacement.

Normal keystrokes are observed without interception. Recognised words and
explicitly selected text can trigger replacement.
"""

from collections import deque
import ctypes as C
import ctypes.util
from functools import wraps
import queue
import threading
import time

from .background_core import WordTracker
from .shortcut import parse_shortcut, convert_selection

TERMINALS = ('terminal', 'terminator', 'kitty', 'alacritty', 'konsole', 'xterm',
             'wezterm', 'tilix', 'terminology', 'guake', 'yakuake', 'tabby')


def keyboard_locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


class XkbState(C.Structure):
    _fields_ = [('group', C.c_ubyte), ('locked_group', C.c_ubyte),
                ('base_group', C.c_ushort), ('latched_group', C.c_ushort),
                *[(name, C.c_ubyte) for name in ('mods', 'base_mods', 'latched_mods',
                  'locked_mods', 'compat_state', 'grab_mods', 'compat_grab_mods',
                  'lookup_mods', 'compat_lookup_mods')], ('ptr_buttons', C.c_ushort)]


class XEvent(C.Union):
    # Xlib reserves 24 native longs for every event, including XKB events.
    _fields_ = [('type', C.c_int), ('padding', C.c_long * 24)]


class Keyboard:
    def __init__(self):
        self.lock = threading.RLock()
        self.x11 = C.CDLL(ctypes.util.find_library('X11'))
        self.xkb = C.CDLL(ctypes.util.find_library('xkbcommon'))
        self.x11.XOpenDisplay.argtypes = [C.c_char_p]
        self.x11.XOpenDisplay.restype = C.c_void_p
        self.x11.XCloseDisplay.argtypes = [C.c_void_p]
        self.x11.XkbKeycodeToKeysym.argtypes = [C.c_void_p, C.c_ubyte, C.c_int, C.c_int]
        self.x11.XkbKeycodeToKeysym.restype = C.c_ulong
        self.x11.XkbGetState.argtypes = [C.c_void_p, C.c_uint, C.POINTER(XkbState)]
        self.x11.XkbLockGroup.argtypes = [C.c_void_p, C.c_uint, C.c_uint]
        self.x11.XkbQueryExtension.argtypes = [C.c_void_p] + [C.POINTER(C.c_int)] * 5
        self.x11.XkbSelectEvents.argtypes = [C.c_void_p, C.c_uint, C.c_uint, C.c_uint]
        self.x11.XPending.argtypes = [C.c_void_p]
        self.x11.XNextEvent.argtypes = [C.c_void_p, C.POINTER(XEvent)]
        self.x11.XkbRefreshKeyboardMapping.argtypes = [C.POINTER(XEvent)]
        self.x11.XRefreshKeyboardMapping.argtypes = [C.POINTER(XEvent)]
        self.x11.XSync.argtypes = [C.c_void_p, C.c_int]
        self.xkb.xkb_keysym_to_utf32.argtypes = [C.c_uint32]
        self.xkb.xkb_keysym_to_utf32.restype = C.c_uint32
        self.display = self.x11.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError('Cannot connect to the X11 desktop.')
        opcode, event_base, error_base, major, minor = (C.c_int() for _ in range(5))
        if not self.x11.XkbQueryExtension(self.display, C.byref(opcode), C.byref(event_base),
                                         C.byref(error_base), C.byref(major), C.byref(minor)):
            self.close()
            raise RuntimeError('The X server needs the XKB extension.')
        self.xkb_event_base = event_base.value
        # GNOME can replace/reorder the map after login or a layout change.
        # XkbKeycodeToKeysym otherwise keeps its first map indefinitely.
        if not self.x11.XkbSelectEvents(self.display, 0x100, 3, 3):
            self.close()
            raise RuntimeError('Cannot observe X11 keyboard mapping changes.')
        self.x11.XSync(self.display, False)

    def _refresh_mapping(self):
        while self.x11.XPending(self.display):
            event = XEvent()
            self.x11.XNextEvent(self.display, C.byref(event))
            if event.type == self.xkb_event_base:
                self.x11.XkbRefreshKeyboardMapping(C.byref(event))
            elif event.type == 34:  # Core MappingNotify fallback.
                self.x11.XRefreshKeyboardMapping(C.byref(event))

    @keyboard_locked
    def symbol(self, keycode, group, level=0):
        self._refresh_mapping()
        return self._symbol(keycode, group, level)

    def _symbol(self, keycode, group, level=0):
        symbol = self.x11.XkbKeycodeToKeysym(self.display, keycode, group, level)
        # Space, modifiers and other shared keys have only one XKB group.
        if not symbol and group:
            symbol = self.x11.XkbKeycodeToKeysym(self.display, keycode, 0, level)
        return symbol

    @keyboard_locked
    def character(self, keycode, state):
        state = self.normalize_state(state)
        group = (state >> 13) & 3
        shifted = bool(state & 1)
        symbol = self.symbol(keycode, group, int(shifted))
        code = self.xkb.xkb_keysym_to_utf32(symbol)
        if not code:
            return None
        char = chr(code)
        if state & 2 and char.isalpha():
            char = char.swapcase()
        return char

    @keyboard_locked
    def normalize_state(self, state):
        # RECORD and legacy X clients can encode a nonzero keyboard group as
        # Mod5 rather than XKB's group bits. Distinguish that from real AltGr.
        if state & 128 and not state & (3 << 13):
            current = self.state()
            if current.group and not current.mods & 128:
                state = (state & ~128) | (current.group << 13)
        return state

    @keyboard_locked
    def state(self):
        state = XkbState()
        if self.x11.XkbGetState(self.display, 0x100, C.byref(state)) != 0:
            raise RuntimeError('Cannot read X11 keyboard state.')
        return state

    @keyboard_locked
    def lock_group(self, group):
        if not self.x11.XkbLockGroup(self.display, 0x100, group):
            raise RuntimeError('Cannot switch the X11 keyboard group.')
        self.x11.XSync(self.display, False)

    @keyboard_locked
    def group_for(self, language):
        # Inspect actual configured keymaps; do not assume their group order.
        self._refresh_mapping()
        wanted = 'q' if language == 'en' else 'й'
        for group in range(4):
            for keycode in range(8, 256):
                if self.xkb.xkb_keysym_to_utf32(self._symbol(keycode, group)) == ord(wanted):
                    return group
        return None

    @keyboard_locked
    def strokes(self, text, group, caps):
        self._refresh_mapping()
        result = []
        for char in text:
            found = None
            for level in (0, 1):
                for code in range(8, 256):
                    scalar = self.xkb.xkb_keysym_to_utf32(self._symbol(code, group, level))
                    rendered = chr(scalar) if scalar else ''
                    if caps and rendered.isalpha():
                        rendered = rendered.swapcase()
                    if rendered == char:
                        found = (code, bool(level))
                        break
                if found:
                    break
            if found is None:
                return None
            result.append(found)
        return result

    @keyboard_locked
    def close(self):
        if self.display:
            self.x11.XCloseDisplay(self.display)
            self.display = None


class X11Monitor:
    def __init__(self, config, dictionaries, on_status=lambda _: None, layout_switcher=None):
        self.config = config
        self.tracker = WordTracker(dictionaries, config.data['minimum_word_length'])
        self.on_status = on_status
        self.layout_switcher = layout_switcher
        self._protected = False
        self.protected_focus = None
        self.synthetic = deque()
        self.running = False
        self.control = self.recording = self.keyboard = None
        self.context = None
        self.thread = None
        self.corrections = 0
        self.last_skip = ''
        self.input_serial = 0
        self.replay_pending = False
        self.jobs = queue.Queue()
        self.stopping = threading.Event()
        self.replay_thread = None

    @property
    def protected(self):
        return self._protected

    @protected.setter
    def protected(self, value):
        self._protected = bool(value)
        self.protected_focus = None
        if self._protected and self.control:
            self.protected_focus = self.focus()[0]

    def start(self):
        import Xlib.threaded  # noqa: F401: serialize Xlib requests from stop/callback.
        from Xlib import display, X
        from Xlib.ext import record

        self.control = display.Display()
        self.recording = display.Display()
        if not self.recording.has_extension('RECORD') or not self.control.has_extension('XTEST'):
            raise RuntimeError('The X server needs RECORD and XTEST extensions.')
        self.keyboard = Keyboard()
        self.context = self.recording.record_create_context(0, [record.AllClients], [{
            'core_requests': (0, 0), 'core_replies': (0, 0),
            'ext_requests': (0, 0, 0, 0), 'ext_replies': (0, 0, 0, 0),
            'delivered_events': (0, 0), 'device_events': (X.KeyPress, X.ButtonRelease),
            'errors': (0, 0), 'client_started': False, 'client_died': False,
        }])
        self.recording.flush()
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True, name='en-ua-x11')
        self.thread.start()
        self.replay_thread = threading.Thread(target=self._replay_jobs, daemon=True,
                                              name='en-ua-replay')
        self.replay_thread.start()

    def _replay_jobs(self):
        while not self.stopping.is_set():
            try:
                plan, serial = self.jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if isinstance(plan, tuple):
                    self.replace_selection(plan[1], serial)
                else:
                    self.replace(plan, serial)
            except Exception as error:
                self.on_status(f'Correction skipped: {type(error).__name__}')
            finally:
                self.replay_pending = False
                self.jobs.task_done()

    def _run(self):
        try:
            self.recording.record_enable_context(self.context, self._record)
        except Exception as error:
            if self.running:
                self.on_status(f'Background correction stopped: {type(error).__name__}')
        finally:
            self.running = False

    def stop(self):
        self.running = False
        self.stopping.set()
        if self.control and self.context is not None:
            self.control.record_disable_context(self.context)
            self.control.flush()
        if self.thread:
            self.thread.join(timeout=2)
        if self.replay_thread:
            self.replay_thread.join(timeout=2)
        if ((self.thread and self.thread.is_alive()) or
                (self.replay_thread and self.replay_thread.is_alive())):
            return
        if self.recording:
            self.recording.close()
        if self.control:
            self.control.close()
        if self.keyboard:
            self.keyboard.close()

    def focus(self):
        window = self.control.get_input_focus().focus
        focus_id = getattr(window, 'id', 0)
        # Apps without AT-SPI events cannot keep a previous app's password
        # guard latched. Preserve protection while its X11 window is focused.
        if self.protected_focus is not None and focus_id != self.protected_focus:
            self.protected = False
        if not hasattr(window, 'id'):
            return 0, ''
        # Walk to the application window without reading document titles/text.
        for _ in range(12):
            try:
                wm_class = window.get_wm_class()
                if wm_class:
                    return focus_id, ' '.join(wm_class).lower()
                parent = window.query_tree().parent
                if parent.id == window.id:
                    break
                window = parent
            except Exception:
                break
        return focus_id, ''

    def allowed(self, app, manual=False):
        if not self.config.data['enabled'] or self.protected or not app:
            return False
        if any(str(name).lower() in app for name in self.config.data['excluded_apps'] if name):
            return False
        return self.config.data['correct_in_terminals'] or not any(name in app for name in TERMINALS)

    def _record(self, reply):
        from Xlib import X
        from Xlib.ext import record
        from Xlib.protocol import rq

        if reply.category != record.FromServer or reply.client_swapped:
            return
        data = reply.data
        try:
            while data:
                event, data = rq.EventField(None).parse_binary_value(data, self.recording.display, None, None)
                if event.type in (X.KeyPress, X.KeyRelease):
                    signature = (event.type, event.detail)
                    if self.synthetic and signature == self.synthetic[0]:
                        self.synthetic.popleft()
                        continue
                    if self.synthetic:
                        # Real input interleaved with replacement: invalidate
                        # tracking and consume only the remaining known events.
                        self.tracker.reset(blocked=True)
                        self.input_serial += 1
                        continue
                if event.type in (X.KeyPress, X.ButtonPress):
                    self.input_serial += 1
                focus, app = self.focus()
                if not self.allowed(app, manual=True):
                    self.tracker.reset()
                    continue
                if event.type == X.ButtonPress:
                    self.tracker.reset(blocked=True)
                elif event.type == X.KeyPress:
                    state = self.keyboard.normalize_state(event.state)
                    symbol = self.keyboard.symbol(event.detail, (state >> 13) & 3)
                    shortcut = parse_shortcut(self.config.data['selection_shortcut'])
                    if shortcut and (state & (1 | 4 | 8 | 64 | 128)) == shortcut[0] and (symbol == shortcut[1] or self.keyboard.symbol(event.detail, self.keyboard.group_for('en') or 0) == shortcut[1]):
                        self.tracker.reset(blocked=True)
                        if not self.replay_pending:
                            self.replay_pending = True
                            self.jobs.put((('selection', focus), self.input_serial))
                        continue
                    if not self.config.data['enabled']:
                        continue
                    if symbol in (0xffe1, 0xffe2, 0xffe3, 0xffe4, 0xffe9, 0xffea,
                                  0xffeb, 0xffec, 0xffe5, 0xfe03, 0xff7f):
                        continue
                    self.tracker.minimum = self.config.data['minimum_word_length']
                    char = '\b' if symbol == 0xff08 else self.keyboard.character(event.detail, state)
                    if char and not char.isprintable() and char != '\b':
                        char = None
                    self.tracker.press(char, focus, event.time,
                                       shortcut=bool(state & (4 | 8 | 64 | 128)))
                elif event.type == X.KeyRelease and self.config.data['enabled']:
                    if self.keyboard.symbol(event.detail, (event.state >> 13) & 3) == 0x20:
                        plan = self.tracker.release_space(focus)
                        if plan and not self.replay_pending:
                            self.replay_pending = True
                            self.jobs.put((plan, self.input_serial))
        except Exception as error:
            self.tracker.reset(blocked=True)
            self.synthetic.clear()
            self.on_status(f'Correction skipped: {type(error).__name__}')

    def replace_selection(self, focus, serial):
        """Read the X11 primary selection and replace it with mapped key events."""
        from Xlib import X
        from gi.repository import Gtk, Gdk, GLib

        # Wait until the shortcut is released before replaying any keys.
        deadline = time.monotonic() + 2
        while any(self.control.query_keymap()) and time.monotonic() < deadline:
            if serial != self.input_serial or self.stopping.wait(0.01):
                return
        if any(self.control.query_keymap()):
            self.last_skip = 'shortcut keys still held'
            return
        result = []
        ready = threading.Event()

        def read_selection():
            try:
                result.append(Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY).wait_for_text())
            finally:
                ready.set()
            return False

        GLib.idle_add(read_selection)
        if not ready.wait(2) or not result or not result[0]:
            self.last_skip = 'no selected text'
            return
        converted = convert_selection(result[0])
        if not converted:
            self.last_skip = 'selection has no clear English or Ukrainian text'
            return
        text, language = converted
        current_focus, app = self.focus()
        if serial != self.input_serial or current_focus != focus or not self.allowed(app, manual=True):
            self.last_skip = 'focus or input changed before selection conversion'
            return
        state = self.keyboard.state()
        group = self.keyboard.group_for(language)
        if group is None:
            self.last_skip = 'target keyboard layout is unavailable'
            return
        if self.keyboard.strokes(text, group, bool(state.locked_mods & 2)) is None:
            self.last_skip = 'selection contains unsupported characters'
            return
        previous = next((lang for lang in ('en', 'uk') if self.keyboard.group_for(lang) == state.group), None)
        if not self.config.data['switch_layout'] and previous is None:
            self.last_skip = 'cannot restore an unsupported input source'
            return
        if self.layout_switcher:
            group = self.layout_switcher.switch(self, language, serial, focus)
            if group is None:
                return
        else:
            self.keyboard.lock_group(group)
            if not self._settle_group(group, serial):
                return
        strokes = self.keyboard.strokes(text, group, bool(state.locked_mods & 2))
        current_focus, app = self.focus()
        if (strokes is None or serial != self.input_serial or current_focus != focus
                or not self.allowed(app, manual=True) or any(self.control.query_keymap())
                or self.keyboard.state().group != group):
            self.last_skip = 'selection contains unsupported characters or focus changed'
        else:
            shift = self.control.keysym_to_keycode(0xffe1)
            events = []
            for code, shifted in strokes:
                if shifted:
                    events.append((X.KeyPress, shift))
                events.extend(((X.KeyPress, code), (X.KeyRelease, code)))
                if shifted:
                    events.append((X.KeyRelease, shift))
            self.synthetic.extend(events)
            for event_type, code in events:
                self.control.xtest_fake_input(event_type, code, time=2)
            self.control.sync()
            self.corrections += 1
            self.last_skip = ''
        if not self.config.data['switch_layout'] and serial == self.input_serial:
            self.stopping.wait(0.05)
            if self.layout_switcher:
                self.layout_switcher.switch(self, previous, serial, focus)
            else:
                self.keyboard.lock_group(state.locked_group)

    def _settle_group(self, group, serial, *, ready=None, stable_for=0.08, timeout=0.3):
        """Wait for clients to observe a stable group, while RECORD keeps running.

        XSync confirms only server processing. It cannot confirm that GTK or
        an asynchronous input method has consumed the group notification.
        """
        stable_since = None
        stable_group = None
        desktop_ready = True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stopping.is_set():
                self.last_skip = 'switcher stopping'
                return False
            if serial != self.input_serial:
                self.last_skip = 'new input while switching layout'
                return False
            current = self.keyboard.state().group
            desktop_ready = ready is None or ready()
            if desktop_ready and (group is None or current == group):
                if stable_since is None or current != stable_group:
                    stable_since = time.monotonic()
                    stable_group = current
                if time.monotonic() - stable_since >= stable_for:
                    return True
            else:
                stable_since = None
            self.stopping.wait(0.005)
        self.last_skip = ('desktop keyboard grab did not end' if not desktop_ready
                          else 'keyboard layout did not settle')
        return False

    def replace(self, plan, serial):
        from Xlib import X

        focus, app = self.focus()
        state = self.keyboard.state()
        # Fail closed if focus changed or another key is physically down.
        if (serial != self.input_serial or focus != plan.focus or not self.allowed(app)
                or state.mods & (1 | 4 | 8 | 64 | 128)):
            self.last_skip = f'focus/modifiers: {state.mods}'
            return
        if any(self.control.query_keymap()):
            self.last_skip = 'key still down'
            return
        group = self.keyboard.group_for(plan.language)
        if group is None:
            self.on_status('Add both standard English (US) and Ukrainian layouts in Ubuntu Keyboard settings.')
            return
        previous_language = next((language for language in ('en', 'uk')
                                  if self.keyboard.group_for(language) == state.group), None)
        if self.layout_switcher:
            if not self.config.data['switch_layout'] and previous_language is None:
                self.last_skip = 'cannot restore an unsupported input source'
                return
            group = self.layout_switcher.switch(self, plan.language, serial, plan.focus)
            if group is None:
                return
        else:
            self.keyboard.lock_group(group)
            if not self._settle_group(group, serial):
                return
        # GNOME may replace the map when activating a source. Build strokes
        # from the resulting map, after its temporary keyboard grab has ended.
        strokes = self.keyboard.strokes(plan.corrected + ' ', group, bool(state.locked_mods & 2))
        if strokes is None:
            self.last_skip = 'unavailable character'
            return
        backspace = self.control.keysym_to_keycode(0xff08)
        shift = self.control.keysym_to_keycode(0xffe1)
        deletions = []
        for _ in range(len(plan.original) + 1):
            deletions += [(X.KeyPress, backspace), (X.KeyRelease, backspace)]
        events = []
        for code, shifted in strokes:
            if shifted:
                events.append((X.KeyPress, shift))
            events += [(X.KeyPress, code), (X.KeyRelease, code)]
            if shifted:
                events.append((X.KeyRelease, shift))
        # Recheck before erasing anything: the observer can cancel this job
        # when new input arrives during the layout-settling interval.
        focus, app = self.focus()
        if (serial != self.input_serial or focus != plan.focus or not self.allowed(app)
                or any(self.control.query_keymap())):
            self.last_skip = 'focus or input changed before replacement'
            return
        if self.keyboard.state().group != group:
            self.last_skip = 'layout changed before replacement'
            return
        self.synthetic.extend(deletions + events)
        for batch in (deletions, events):
            for event_type, code in batch:
                # A small server-side delay lets asynchronous IM clients
                # consume each event; a zero-delay burst can lose/reorder it.
                self.control.xtest_fake_input(event_type, code, time=2)
            self.control.sync()
        self.corrections += 1
        self.last_skip = ''
        if not self.config.data['switch_layout']:
            # Let the app consume the target-group key events before restoring.
            self.stopping.wait(0.05)
            if serial == self.input_serial:
                if self.layout_switcher:
                    self.layout_switcher.switch(self, previous_language, serial, plan.focus)
                else:
                    self.keyboard.lock_group(state.locked_group)
        # The observer already cleared the completed token and ignores our
        # replay. Do not reset it here: the user may have begun the next word
        # while this worker was returning from XSync.
