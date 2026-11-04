import unittest

from en_ua.shortcut import convert_selection, parse_shortcut


class SelectionTests(unittest.TestCase):
    def test_converts_both_directions_and_case(self):
        self.assertEqual(convert_selection('Ghbdtn cdsn'), ('Привет світ', 'uk'))
        self.assertEqual(convert_selection('Руддщ цщкдв'), ('Hello world', 'en'))

    def test_no_language_or_tie_is_ignored(self):
        self.assertIsNone(convert_selection('123'))
        self.assertIsNone(convert_selection('a я'))

    def test_shortcuts_validate_modifiers_and_keys(self):
        self.assertEqual(parse_shortcut('Ctrl+Alt+Space'), (12, 32))
        self.assertEqual(parse_shortcut('Super+F8'), (64, 0xffc5))
        self.assertIsNone(parse_shortcut('Space'))
        self.assertIsNone(parse_shortcut('Ctrl+Ctrl+Space'))
        self.assertIsNone(parse_shortcut('Ctrl+NoSuchKey'))
