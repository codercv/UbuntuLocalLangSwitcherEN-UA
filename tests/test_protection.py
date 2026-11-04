from types import SimpleNamespace
import unittest

from en_ua.protection import PasswordFocusGuard
from en_ua.background_core import WordTracker
from tests.helpers import TestDictionaries


class Field:
    def __init__(self, role):
        self.role = role

    def get_role(self):
        if isinstance(self.role, Exception):
            raise self.role
        return self.role


class PasswordProtectionTests(unittest.TestCase):
    def setUp(self):
        self.monitor = SimpleNamespace(protected=False,
                                       tracker=SimpleNamespace(reset=lambda **_: None))
        self.guard = PasswordFocusGuard(self.monitor, 'password')

    def focus(self, source, focused=True):
        self.guard(SimpleNamespace(source=source, detail1=int(focused)))

    def test_password_blur_resumes_apps_without_accessibility_events(self):
        password = Field('password')
        self.focus(password)
        self.assertTrue(self.monitor.protected)
        self.focus(password, False)
        self.assertFalse(self.monitor.protected)

    def test_late_blur_does_not_unprotect_another_password_field(self):
        first, second = Field('password'), Field('password')
        self.focus(first)
        self.focus(second)
        self.focus(first, False)
        self.assertTrue(self.monitor.protected)
        self.focus(second, False)
        self.assertFalse(self.monitor.protected)

    def test_unknown_field_is_protected_until_blur(self):
        field = Field(RuntimeError('accessible disappeared'))
        self.focus(field)
        self.assertTrue(self.monitor.protected)
        self.focus(field, False)
        self.assertFalse(self.monitor.protected)

    def test_normal_field_resumes_correction(self):
        self.focus(Field('password'))
        self.focus(Field('text'))
        self.assertFalse(self.monitor.protected)

    def use_word_tracker(self):
        self.monitor.tracker = WordTracker(TestDictionaries())

    def type_word(self):
        for i, char in enumerate('ghbdsn '):
            self.monitor.tracker.press(char, 10, 100 + i * 10)
        result = self.monitor.tracker.release_space(10)
        self.assertIsNotNone(result)
        self.assertEqual(result.corrected, 'привіт')

    def test_first_word_after_normal_focus_is_corrected(self):
        self.use_word_tracker()
        self.focus(Field('text'))
        self.type_word()

    def test_first_word_after_password_blur_is_corrected(self):
        self.use_word_tracker()
        password = Field('password')
        self.focus(password)
        self.focus(password, False)
        self.type_word()

    def test_normal_accessibility_focus_does_not_discard_an_active_word(self):
        self.use_word_tracker()
        self.monitor.tracker.press('g', 10, 100)
        self.focus(Field('text'))
        for i, char in enumerate('hbdsn '):
            self.monitor.tracker.press(char, 10, 110 + i * 10)
        self.assertEqual(self.monitor.tracker.release_space(10).corrected, 'привіт')
