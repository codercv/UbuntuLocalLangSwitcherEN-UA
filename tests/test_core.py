import unittest

from en_ua.core import Composer, Detector, US, UA, US_SHIFT, UA_SHIFT, convert
from tests.helpers import TestDictionaries


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.detector = Detector(TestDictionaries())
        self.composer = Composer(self.detector)

    def type_word(self, text):
        for char in text:
            self.composer.append(char)

    def test_full_standard_ukrainian_mapping_roundtrip(self):
        self.assertEqual(convert(US + US_SHIFT, 'uk'), UA + UA_SHIFT)
        self.assertEqual(convert(UA + UA_SHIFT, 'en'), US + US_SHIFT)

    def test_ukrainian_and_case(self):
        self.type_word('Ghbdsn')
        self.assertEqual(self.composer.finish(), 'Привіт')
        self.assertEqual(self.composer.language, 'uk')

    def test_english_while_ukrainian_active(self):
        self.composer.language = 'uk'
        self.type_word('Hello')
        self.assertEqual(self.composer.preview, 'Руддщ')
        self.assertEqual(self.composer.finish(), 'Hello')
        self.assertEqual(self.composer.language, 'en')

    def test_convert_existing_wrong_layout_text(self):
        self.assertEqual(convert('Руддщ цщкдв!', 'en'), 'Hello world!')
        self.assertEqual(convert('GhbdSn', 'uk'), 'ПривІт')

    def test_ambiguous_and_unknown_stay_in_current_language(self):
        for raw in ('cat', 'zxqv'):
            for language in ('en', 'uk'):
                result = self.detector.decide(raw, language)
                self.assertFalse(result.changed)
                self.assertEqual(result.language, language)

    def test_short_words_not_guessed(self):
        self.assertEqual(self.detector.decide('ds', 'en').text, 'ds')

    def test_ukrainian_letters_on_punctuation_keys(self):
        for word in ('ґанок', "п'ять", 'жук'):
            raw = convert(word, 'en')
            self.assertEqual(self.detector.decide(raw).text, word)

    def test_manual_override_survives_dictionary(self):
        self.type_word('hello')
        self.composer.toggle()
        self.assertEqual(self.composer.finish(), 'руддщ')

    def test_identifiers_and_urls_are_literal(self):
        for token in ('name@example.com', 'https://example.com', 'some_var', '2026', 'v2.0'):
            self.composer.language = 'uk'
            self.type_word(token)
            self.assertEqual(self.composer.finish(), token)

    def test_punctuation_preserved_with_correct_english(self):
        self.assertEqual(self.detector.decide('hello,').text, 'hello,')
        self.assertEqual(self.detector.decide('hello!').text, 'hello!')

    def test_edit_and_clear(self):
        self.type_word('ghbdsnx')
        self.composer.backspace()
        self.assertEqual(self.composer.finish(), 'привіт')
        self.assertEqual(self.composer.raw, '')
        self.type_word('hello')
        self.composer.clear()
        self.assertEqual(self.composer.finish(), '')


if __name__ == '__main__':
    unittest.main()
