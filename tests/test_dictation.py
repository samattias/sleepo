"""Dictation with FluidVoice (assist/dictation.py): its shortcut is read from its own settings, whatever form they take, and
described for the page; nothing here presses a key. Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import unittest

from assist import dictation


class Shortcut(unittest.TestCase):
    def test_reads_fluidvoice_settings(self):
        fn = {"kind": "keyboard", "modifierKeyCodes": [63], "keyCode": 63, "modifierFlagsRawValue": 0}
        self.assertEqual(dictation.parse_shortcut({"PrimaryDictationShortcuts": json.dumps([fn]).encode()}), fn)   # as stored: JSON bytes, a list
        self.assertEqual(dictation.parse_shortcut({"HotkeyShortcutKey": json.dumps(fn)}), fn)
        self.assertEqual(dictation.parse_shortcut({}), dictation.DEFAULT)
        self.assertEqual(dictation.parse_shortcut({"HotkeyShortcutKey": b"not json"}), dictation.DEFAULT)

    def test_describes_it(self):
        self.assertEqual(dictation.describe(dictation.DEFAULT), "Fn")
        self.assertEqual(dictation.describe({"keyCode": 61, "modifierFlagsRawValue": 0}), "right Option")
        self.assertEqual(dictation.describe({"keyCode": 2, "modifierFlagsRawValue": 0x100000 | 0x020000}), "Shift + Command + key 2")


if __name__ == "__main__":
    unittest.main()
