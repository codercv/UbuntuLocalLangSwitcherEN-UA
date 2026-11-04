"""Layout conversion and conservative detection, independent of the desktop."""

from dataclasses import dataclass
import re

# Standard US and Ukrainian (XKB ua) key positions, including Shift.
US = "`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./"
UA = "'1234567890-=йцукенгшщзхїґфівапролджєячсмитьбю."
US_SHIFT = '~!@#$%^&*()_+QWERTYUIOP{}|ASDFGHJKL:"ZXCVBNM<>?'
UA_SHIFT = 'ʼ!"№;%:?*()_+ЙЦУКЕНГШЩЗХЇҐФІВАПРОЛДЖЄЯЧСМИТЬБЮ,'
TO_UA = str.maketrans(US + US_SHIFT, UA + UA_SHIFT)
TO_EN = str.maketrans(UA + UA_SHIFT, US + US_SHIFT)
LETTERS = {'en': 'a-zA-Z', 'uk': 'а-яА-ЯіІїЇєЄґҐ'}


def is_identifier(raw):
    return (any(c.isdigit() or c in '=_' for c in raw) or '://' in raw
            or ('@' in raw and any(c.isalpha() for c in raw)))


def convert(text, target):
    """Convert key positions (not transliteration), preserving case."""
    if target not in ('en', 'uk'):
        raise ValueError('target must be en or uk')
    return text.translate(TO_UA if target == 'uk' else TO_EN)


class Dictionaries:
    """Use complete installed dictionaries; never silently fall back to a toy list."""

    def __init__(self):
        try:
            import enchant
            self.dicts = {lang: enchant.Dict(tag) for lang, tag in
                          [('en', 'en_US'), ('uk', 'uk_UA')]}
        except Exception as error:
            raise RuntimeError(
                'English and Ukrainian dictionaries are required. Install: '
                'sudo apt install python3-enchant hunspell-en-us hunspell-uk'
            ) from error

    def check(self, word, language):
        return self.dicts[language].check(word)


@dataclass(frozen=True)
class Decision:
    text: str
    language: str
    changed: bool


class Detector:
    def __init__(self, dictionaries):
        self.dictionaries = dictionaries

    def known(self, text, language):
        # Punctuation around a word is allowed; punctuation inside must only be
        # an apostrophe. This also handles keys like [, ; and , that are letters
        # in Ukrainian, without prematurely splitting them in the input buffer.
        letters = LETTERS[language]
        body = re.sub(f'^[^{letters}]+|[^{letters}]+$', '', text)
        if not re.fullmatch(f'[{letters}]+(?:[\x27’ʼ][{letters}]+)*', body):
            return False
        if len(body.replace("'", '').replace('’', '').replace('ʼ', '')) < 3:
            return False
        return self.dictionaries.check(body, language)

    def decide(self, raw_us, preferred='en', ukrainian=None):
        ukrainian = convert(raw_us, 'uk') if ukrainian is None else ukrainian
        current = raw_us if preferred == 'en' else ukrainian
        other = 'uk' if preferred == 'en' else 'en'
        candidate = raw_us if other == 'en' else ukrainian
        # Leave identifiers, URLs, addresses and numbers in their physical US
        # representation. Pause is still recommended for code and shell input.
        if is_identifier(raw_us):
            return Decision(raw_us, preferred, False)
        if self.known(current, preferred) or not self.known(candidate, other):
            return Decision(current, preferred, False)
        return Decision(candidate, other, True)


class Composer:
    """One uncommitted token. No surrounding-text reads or clipboard access."""

    def __init__(self, detector):
        self.detector = detector
        self.language = 'en'
        self.raw = ''
        self.ukrainian = ''
        self.manual = False
        self.literal = False

    @property
    def preview(self):
        return self.raw if self.language == 'en' or self.literal else self.ukrainian

    def append(self, char, caps_lock=False):
        self.raw += char
        ukrainian = convert(char, 'uk')
        # US punctuation keysyms ignore Caps Lock; the corresponding Ukrainian
        # letters must still obey it. US alphabetic keysyms already include it.
        if caps_lock and not char.isalpha() and ukrainian.isalpha():
            ukrainian = ukrainian.swapcase()
        self.ukrainian += ukrainian
        # An identifier remains literal for its entire token, including after
        # a long buffer is flushed by the frontend.
        self.literal = is_identifier(self.raw)

    def backspace(self):
        self.raw = self.raw[:-1]
        self.ukrainian = self.ukrainian[:-1]
        self.literal = is_identifier(self.raw)

    def toggle(self):
        self.language = 'uk' if self.language == 'en' else 'en'
        self.manual = True
        self.literal = False

    def clear(self):
        self.raw = ''
        self.ukrainian = ''
        self.manual = False
        self.literal = False

    def finish(self, automatic=True):
        result = self.preview
        if self.raw and automatic and not self.manual and not self.literal:
            decision = self.detector.decide(self.raw, self.language, self.ukrainian)
            result, self.language = decision.text, decision.language
        self.clear()
        return result
