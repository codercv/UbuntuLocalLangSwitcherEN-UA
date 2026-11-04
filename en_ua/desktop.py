"""Use GNOME's normal source-switch shortcut and wait for its keyboard grab."""


class KeyboardGrabTracker:
    """Observe XI/core grab focus notifications without grabbing any input."""

    def __init__(self, control, focus):
        self.control = control
        self.focus = focus
        self.window = control.create_resource_object('window', focus)
        self.previous_mask = None
        self.grabbed = False

    def __enter__(self):
        self.previous_mask = self.window.get_attributes().your_event_mask
        self.window.change_attributes(event_mask=self.previous_mask | (1 << 21))
        self.control.sync()
        self()
        return self

    def __call__(self):
        while self.control.pending_events():
            event = self.control.next_event()
            if event.type == 34:  # MappingNotify on this independent client.
                self.control.refresh_keyboard_mapping(event)
                continue
            window = getattr(event, 'window', None)
            if getattr(window, 'id', window) != self.focus:
                continue
            if event.type in (9, 10):  # FocusIn and FocusOut share mode semantics.
                if event.mode in (1, 3):  # NotifyGrab / NotifyWhileGrabbed
                    self.grabbed = True
                elif event.mode in (0, 2):  # NotifyNormal / NotifyUngrab
                    self.grabbed = False
        return not self.grabbed

    def __exit__(self, *_):
        if self.previous_mask is not None:
            try:
                self.window.change_attributes(event_mask=self.previous_mask)
                self.control.flush()
            except Exception:
                # A window may have closed while its correction was cancelled.
                pass


class GnomeLayoutSwitcher:
    def __init__(self, keyval, modifiers=(), source_count=2, alternatives=()):
        # Normalized modifier keysyms keep this class independent of GTK/GI.
        self.bindings = [(keyval, tuple(modifiers)), *alternatives]
        self.source_count = max(1, min(32, int(source_count)))

    def _shortcut(self, control):
        for keyval, modifiers in self.bindings:
            if not keyval or not modifiers:
                continue
            code = control.keysym_to_keycode(keyval)
            modifier_codes = [control.keysym_to_keycode(symbol) for symbol in modifiers]
            if code and all(modifier_codes):
                return ([(2, modifier) for modifier in modifier_codes]
                        + [(2, code), (3, code)]
                        + [(3, modifier) for modifier in reversed(modifier_codes)])
        return None

    @staticmethod
    def _safe(monitor, serial, focus):
        current_focus, app = monitor.focus()
        if (monitor.stopping.is_set() or serial != monitor.input_serial
                or current_focus != focus or not monitor.allowed(app)
                or any(monitor.control.query_keymap())):
            monitor.last_skip = 'Input or focus changed before GNOME layout switch'
            return False
        return True

    def switch(self, monitor, language, serial, focus):
        if not self._safe(monitor, serial, focus):
            return None
        target = monitor.keyboard.group_for(language)
        if target is None:
            monitor.last_skip = 'Requested language is unavailable in the keyboard map'
            return None
        if monitor.keyboard.state().group == target:
            return target
        shortcut = self._shortcut(monitor.control)
        if shortcut is None or self.source_count < 2:
            monitor.last_skip = 'No usable GNOME input-source shortcut with a modifier'
            return None
        try:
            with KeyboardGrabTracker(monitor.control, focus) as ready:
                for _ in range(self.source_count):
                    if not self._safe(monitor, serial, focus):
                        return None
                    monitor.synthetic.extend(shortcut)
                    for event_type, code in shortcut:
                        monitor.control.xtest_fake_input(event_type, code, time=2)
                    monitor.control.sync()
                    if not monitor._settle_group(None, serial, ready=ready, timeout=1.0):
                        return None
                    # Activating a source can install a different/reordered map.
                    target = monitor.keyboard.group_for(language)
                    if target is None:
                        monitor.last_skip = 'Requested language disappeared after GNOME source switch'
                        return None
                    if monitor.keyboard.state().group == target:
                        if self._safe(monitor, serial, focus):
                            return target
                        return None
        except Exception as error:
            monitor.last_skip = f'GNOME layout switch failed: {type(error).__name__}'
            return None
        monitor.last_skip = 'GNOME source cycling did not reach the requested language'
        return None


def create_layout_switcher():
    """Return a GNOME adapter only when the session actually owns Shell's bus."""
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gio, GLib, Gtk
    except (ImportError, ValueError):
        return None
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                               'org.freedesktop.DBus', 'NameHasOwner',
                               GLib.Variant('(s)', ('org.gnome.Shell',)),
                               GLib.VariantType.new('(b)'), Gio.DBusCallFlags.NONE,
                               1000, None)
        if not result.unpack()[0]:
            return None
    except GLib.Error:
        return None

    bindings = []
    source_count = 1
    try:
        settings = Gio.Settings.new('org.gnome.desktop.wm.keybindings')
        sources = Gio.Settings.new('org.gnome.desktop.input-sources')
        source_count = len(sources.get_value('sources').unpack())
        # GDK virtual Super and physical Mod4 represent the same modifier.
        modifiers = ((1, 0xffe1), (4, 0xffe3), (8, 0xffe9),
                     (64 | (1 << 26), 0xffeb))
        supported = 1 | 4 | 8 | 64 | (1 << 26)
        for accelerator in settings.get_strv('switch-input-source'):
            keyval, mask = Gtk.accelerator_parse(accelerator)
            mask = int(mask)
            if keyval and mask and not mask & ~supported:
                bindings.append((keyval, tuple(symbol for flag, symbol in modifiers if mask & flag)))
    except (ValueError, GLib.Error):
        pass
    if not bindings:
        return GnomeLayoutSwitcher(None, source_count=source_count)
    return GnomeLayoutSwitcher(*bindings[0], source_count=source_count, alternatives=bindings[1:])
