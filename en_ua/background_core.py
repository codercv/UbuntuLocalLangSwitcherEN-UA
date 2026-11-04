"""Conservative word tracking for the passive X11 background utility."""

from dataclasses import dataclass
import re

from .core import convert


@dataclass(frozen=True)
class Replacement:
    original: str
    corrected: str
    language: str
    focus: int


class WordTracker:
    """Tracks only freshly typed characters; never reads existing document text."""

    def __init__(self, dictionaries, minimum=4):
        self.dictionaries = dictionaries
        self.minimum = minimum
        self.focus = None
        self.word = ''
        self.pending = None
        self.blocked = False
        self.last_time = 0

    def reset(self, blocked=False):
        self.word = ''
        self.pending = None
        self.blocked = blocked

    def press(self, char, focus, timestamp, shortcut=False):
        if focus != self.focus or timestamp - self.last_time > 4000:
            self.reset()
        self.focus = focus
        self.last_time = timestamp
        self.pending = None
        if shortcut:
            self.reset(blocked=True)
            return
        if char == '\b':
            # Editing invalidates the token; do not guess how an app deletes.
            self.reset(blocked=True)
            return
        if char == ' ':
            if self.word and not self.blocked:
                self.pending = self.decide(self.word, focus)
            self.word = ''
            self.blocked = False
        elif char is None or char.isspace():
            self.reset(blocked=True)
        elif not self.blocked:
            self.word += char
            if len(self.word) > 48:
                self.reset(blocked=True)

    def release_space(self, focus):
        pending = self.pending
        self.pending = None
        return pending if pending and pending.focus == focus else None

    def decide(self, word, focus):
        if len(word) < self.minimum:
            return None
        # Pure words and internal apostrophes only. Punctuation at either end,
        # numbers, paths and identifiers are deliberately left untouched.
        if re.fullmatch(r"[A-Za-z]+(?:'[A-Za-z]+)*", word):
            source, target = 'en', 'uk'
        elif re.fullmatch(r"[а-яА-ЯіІїЇєЄґҐ]+(?:['’ʼ][а-яА-ЯіІїЇєЄґҐ]+)*", word):
            source, target = 'uk', 'en'
        else:
            return None
        candidate = convert(word, target)
        target_pattern = r"[A-Za-z]+(?:'[A-Za-z]+)*" if target == 'en' else r"[а-яА-ЯіІїЇєЄґҐ]+(?:['ʼ][а-яА-ЯіІїЇєЄґҐ]+)*"
        if not re.fullmatch(target_pattern, candidate):
            return None
        if self.dictionaries.check(word, source) or not self.dictionaries.check(candidate, target):
            return None
        return Replacement(word, candidate, target, focus)
