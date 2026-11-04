import unittest

from en_ua.background_core import WordTracker
from tests.helpers import TestDictionaries


class BackgroundPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tracker = WordTracker(TestDictionaries())

    def type(self, text, focus=10, start=100):
        for i, char in enumerate(text):
            self.tracker.press(char, focus, start + i * 10)

    def test_correction_only_after_released_space(self):
        self.type('ghbdsn')
        self.assertIsNone(self.tracker.release_space(10))
        self.tracker.press(' ', 10, 200)
        self.assertEqual(self.tracker.release_space(10).corrected, 'привіт')

    def test_reverse_direction_without_special_input_source(self):
        self.type('руддщ ')
        self.assertEqual(self.tracker.release_space(10).corrected, 'hello')

    def test_good_unknown_short_code_and_punctuation_stay_untouched(self):
        for text in ('hello ', 'привіт ', 'test ', 'cat ', 'xyzzy ', 'v2 ', 'some_var ', 'ghbdsn! ', 'https://hello '):
            self.tracker.reset()
            self.type(text)
            self.assertIsNone(self.tracker.release_space(10), text)

    def test_editing_or_navigation_cancels_correction(self):
        for edit in ('\b', None):
            self.tracker.reset()
            self.type('ghb')
            self.tracker.press(edit, 10, 150)
            self.type('dsn ', start=200)
            self.assertIsNone(self.tracker.release_space(10))

    def test_focus_change_and_interleaved_typing_cancel_pending_replacement(self):
        self.type('ghbdsn ')
        self.assertIsNone(self.tracker.release_space(20))
        self.type('ghbdsn ', start=200)
        self.tracker.press('a', 10, 350)
        self.assertIsNone(self.tracker.release_space(10))

    def test_paste_shortcut_and_very_long_tokens_are_not_corrected(self):
        self.tracker.press('v', 10, 10, shortcut=True)
        self.type('ghbdsn ')
        self.assertIsNone(self.tracker.release_space(10))
        self.type('x' * 60 + 'ghbdsn ', start=500)
        self.assertIsNone(self.tracker.release_space(10))
