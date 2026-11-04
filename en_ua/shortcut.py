"""Portable representation of an X11 shortcut and selected text conversion."""

from .core import convert

MODIFIERS = {'Ctrl': 4, 'Alt': 8, 'Shift': 1, 'Super': 64}
DEFAULT_SHORTCUT = 'Ctrl+Alt+Space'


def parse_shortcut(value):
    parts = value.split('+')
    if len(parts) < 2 or any(part not in MODIFIERS for part in parts[:-1]):
        return None
    if len(set(parts[:-1])) != len(parts[:-1]) or not parts[-1]:
        return None
    from Xlib import XK
    key = 'space' if parts[-1].lower() == 'space' else parts[-1]
    symbol = XK.string_to_keysym(key)
    if not symbol:
        return None
    return sum(MODIFIERS[part] for part in parts[:-1]), symbol


def convert_selection(text):
    english = sum('a' <= c.lower() <= 'z' for c in text)
    ukrainian = sum(c.lower() in 'абвгґдеєжзиіїйклмнопрстуфхцчшщьюя' for c in text)
    if not english and not ukrainian or english == ukrainian:
        return None
    target = 'uk' if english > ukrainian else 'en'
    return convert(text, target), target
