"""Small local settings file; never contains typed text."""

import json
import os
from pathlib import Path

DEFAULTS = {
    'enabled': True,
    'autostart': True,
    'minimum_word_length': 4,
    'switch_layout': True,
    'correct_in_terminals': False,
    'excluded_apps': ['keepassxc', '1password', 'bitwarden', 'keepass', 'en-ua-switcher'],
}


class Config:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'en-ua-switcher/settings.json'
        self.data = dict(DEFAULTS, excluded_apps=list(DEFAULTS['excluded_apps']))
        try:
            stored = json.loads(self.path.read_text())
            for key, default in DEFAULTS.items():
                value = stored.get(key, default)
                if type(value) is type(default):
                    self.data[key] = value
        except (OSError, ValueError, AttributeError):
            pass
        self.data['minimum_word_length'] = max(4, min(12, self.data['minimum_word_length']))
        self.data['excluded_apps'] = [name for name in self.data['excluded_apps'] if isinstance(name, str)]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, indent=2) + '\n')
        temporary.replace(self.path)


def retire_legacy_source():
    """Remove only the obsolete input source installed by versions 0.1.x."""
    from gi.repository import Gio, GLib
    registry = Gio.SettingsSchemaSource.get_default()
    if registry is None or not registry.lookup('org.gnome.desktop.input-sources', True):
        return
    settings = Gio.Settings.new('org.gnome.desktop.input-sources')
    sources = list(settings.get_value('sources').unpack())
    remaining = [entry for entry in sources if entry != ('ibus', 'en-ua-auto')]
    if remaining != sources:
        if not remaining:
            remaining = [('xkb', 'us'), ('xkb', 'ua')]
        if not settings.set_value('sources', GLib.Variant('a(ss)', remaining)):
            raise RuntimeError('Remove the obsolete Automatic input source in Ubuntu Keyboard settings.')
        Gio.Settings.sync()
