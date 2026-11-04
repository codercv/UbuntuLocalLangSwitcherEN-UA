"""Single-instance, quiet GTK application with an Ubuntu tray indicator."""

import json
import os

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, Gio, GLib, AyatanaAppIndicator3 as Indicator

from .config import Config, retire_legacy_source
from .core import Dictionaries
from .shortcut import parse_shortcut
from . import __version__


class TrayApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.en_ua.BackgroundSwitcher',
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.config = Config()
        self.monitor = None
        self.window = None
        self.status_text = 'Starting'
        self.protection_listener = None
        self.indicator = None

    def do_command_line(self, command):
        arguments = command.get_arguments()[1:]
        if '--status' in arguments:
            command.print_literal(json.dumps(self.diagnostics(), indent=2) + '\n')
            return 0
        if '--quit' in arguments:
            self.exit()
            return 0
        if '--background' in arguments and not self.config.data['autostart']:
            return 0
        self.activate()
        if '--setup' in arguments:
            self.settings_window()
        return 0

    def diagnostics(self):
        monitor = self.monitor
        result = {'version': __version__, 'status': self.status_text if self.indicator else 'Not running',
                  'enabled': self.config.data['enabled'],
                  'monitor_running': bool(monitor and monitor.running)}
        if monitor:
            try:
                focus, app = monitor.focus()
            except Exception as error:
                result['desktop_error'] = type(error).__name__
                return result
            result.update(observed_input_events=monitor.input_serial,
                          corrections=monitor.corrections,
                          password_field=monitor.protected,
                          focused_app=app,
                          focused_app_allowed=monitor.allowed(app),
                          layout_backend='GNOME' if monitor.layout_switcher else 'XKB',
                          last_skip=monitor.last_skip)
        return result

    def do_activate(self):
        if self.indicator:
            return
        self.hold()
        self.indicator = Indicator.Indicator.new('en-ua-switcher', 'input-keyboard',
                                                  Indicator.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        self.toggle_item = Gtk.CheckMenuItem(label='Automatic correction enabled')
        self.toggle_item.set_active(self.config.data['enabled'])
        self.toggle_item.connect('toggled', self.toggle)
        menu.append(self.toggle_item)
        self.status_item = Gtk.MenuItem(label='Starting')
        self.status_item.set_sensitive(False)
        menu.append(self.status_item)
        menu.append(Gtk.SeparatorMenuItem())
        for label, callback in [('Settings…', lambda *_: self.settings_window()),
                                ('Quit', self.exit)]:
            item = Gtk.MenuItem(label=label)
            item.connect('activate', callback)
            menu.append(item)
        menu.show_all()
        self.indicator.set_menu(menu)
        if os.environ.get('XDG_SESSION_TYPE') == 'wayland' or not os.environ.get('DISPLAY'):
            self.status('Requires an Ubuntu on Xorg session')
            return
        try:
            retire_legacy_source()
            from .x11 import X11Monitor
            from .desktop import create_layout_switcher
            self.monitor = X11Monitor(self.config, Dictionaries(), self.thread_status,
                                      layout_switcher=create_layout_switcher())
            self.monitor.start()
            self.status(f'Running quietly on X11 · v{__version__}')
            self.accessibility_guard()
        except Exception as error:
            self.status(str(error))

    def thread_status(self, message):
        GLib.idle_add(self.status, message)

    def status(self, message):
        self.status_text = message
        if self.indicator:
            self.status_item.set_label(message)
        if self.window:
            self.status_label.set_text(message)
        return False

    def toggle(self, item):
        self.config.data['enabled'] = item.get_active()
        self.config.save()
        if self.monitor:
            self.monitor.tracker.reset(blocked=True)
        self.indicator.set_icon_full('input-keyboard' if item.get_active() else 'process-stop',
                                     'EN / UA automatic correction')

    def accessibility_guard(self):
        # Use role metadata only; never read accessible text or field values.
        try:
            gi.require_version('Atspi', '2.0')
            from gi.repository import Atspi
            from .protection import PasswordFocusGuard

            self.password_guard = PasswordFocusGuard(self.monitor, Atspi.Role.PASSWORD_TEXT)
            self.protection_listener = Atspi.EventListener.new(self.password_guard, None)
            self.protection_listener.register('object:state-changed:focused')
        except (ValueError, ImportError, GLib.Error):
            pass

    def settings_window(self):
        if self.window:
            self.window.present()
            return
        self.window = Gtk.ApplicationWindow(application=self, title='EN / UA Auto Layout · Settings')
        self.window.set_default_size(560, 460)
        self.window.set_border_width(22)
        self.window.connect('destroy', lambda *_: setattr(self, 'window', None))
        self.window.set_wmclass('en-ua-switcher', 'en-ua-switcher')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.window.add(box)

        def label(text):
            widget = Gtk.Label(label=text, xalign=0)
            widget.set_line_wrap(True)
            widget.set_max_width_chars(68)
            box.pack_start(widget, False, False, 0)
            return widget

        label('Use your normal English and Ukrainian keyboard layouts. '
              'Recognised mistakes are corrected after Space. No special input source or typing mode.')
        self.status_label = label(self.status_text)
        controls = {}
        for key, text in [('enabled', 'Enable automatic correction'),
                          ('autostart', 'Start quietly when I sign in'),
                          ('switch_layout', 'Switch to the corrected language for the next word'),
                          ('correct_in_terminals', 'Also correct words in terminals')]:
            button = Gtk.CheckButton(label=text)
            button.set_active(self.config.data[key])
            controls[key] = button
            box.pack_start(button, False, False, 0)
        label('Terminal correction is off by default to preserve shell commands and password prompts. '
              'Known password fields are skipped, but some apps do not identify them.')
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label='Minimum word length'), False, False, 0)
        minimum = Gtk.SpinButton.new_with_range(4, 12, 1)
        minimum.set_value(self.config.data['minimum_word_length'])
        row.pack_start(minimum, False, False, 0)
        box.pack_start(row, False, False, 0)
        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label='Convert selected text shortcut'), False, False, 0)
        shortcut = Gtk.Entry()
        shortcut.set_text(self.config.data['selection_shortcut'])
        shortcut.set_placeholder_text('Ctrl+Alt+Space')
        row.pack_start(shortcut, True, True, 0)
        box.pack_start(row, False, False, 0)
        label('Enter a key with Ctrl, Alt, Shift or Super, for example Ctrl+Alt+Space.')
        error_label = label('')
        label('Excluded applications (parts of their X11 WM_CLASS, separated by commas)')
        excluded = Gtk.Entry()
        excluded.set_text(', '.join(self.config.data['excluded_apps']))
        box.pack_start(excluded, False, False, 0)
        label('This version supports X11. It uses the X11 primary selection but not the clipboard. '
              'It cannot correct raw Linux virtual consoles or native Wayland apps.')
        actions = Gtk.Box(spacing=10)
        box.pack_start(actions, False, False, 0)

        def save(*_):
            shortcut_value = shortcut.get_text().strip()
            if not parse_shortcut(shortcut_value):
                error_label.set_text('Invalid shortcut. Use e.g. Ctrl+Alt+Space with a valid key name.')
                return
            self.config.data['selection_shortcut'] = shortcut_value
            for key, button in controls.items():
                self.config.data[key] = button.get_active()
            self.config.data['minimum_word_length'] = minimum.get_value_as_int()
            self.config.data['excluded_apps'] = [name.strip().lower() for name in excluded.get_text().split(',') if name.strip()]
            self.config.save()
            self.toggle_item.set_active(self.config.data['enabled'])
            if self.monitor:
                self.monitor.tracker.reset(blocked=True)
            self.window.destroy()

        for text, callback in [('Save', save), ('Cancel', lambda *_: self.window.destroy())]:
            button = Gtk.Button(label=text)
            button.connect('clicked', callback)
            actions.pack_end(button, False, False, 0)
        self.window.show_all()
        self.window.present()

    def exit(self, *_):
        if self.monitor:
            self.monitor.stop()
        if self.protection_listener:
            self.protection_listener.deregister('object:state-changed:focused')
        self.quit()


def run(arguments):
    return TrayApplication().run(['en-ua-switcher', *arguments])
