"""输入层单元测试：调参键匹配（不启动监听器、不碰网络）。"""

from __future__ import annotations

import unittest

from ps5kbm.input_source import adjust_action_for

KEYS = {"r2_up": "wheel_up", "r2_down": "wheel_down", "l2_up": "=", "l2_down": "-"}


class AdjustActionTests(unittest.TestCase):
    def test_default_bindings(self):
        self.assertEqual(adjust_action_for(KEYS, "wheel_up"), "r2_up")
        self.assertEqual(adjust_action_for(KEYS, "wheel_down"), "r2_down")
        self.assertEqual(adjust_action_for(KEYS, "="), "l2_up")
        self.assertEqual(adjust_action_for(KEYS, "-"), "l2_down")

    def test_plus_is_alias_of_equal(self):
        self.assertEqual(adjust_action_for(KEYS, "+"), "l2_up")

    def test_case_insensitive(self):
        keys = {"l2_up": "PageUp", "l2_down": "PageDown"}
        self.assertEqual(adjust_action_for(keys, "pageup"), "l2_up")

    def test_mouse_button_binding(self):
        keys = {"r2_up": "mouse_x1"}
        self.assertEqual(adjust_action_for(keys, "mouse_x1"), "r2_up")

    def test_unbound_returns_empty(self):
        self.assertEqual(adjust_action_for(KEYS, "space"), "")
        self.assertEqual(adjust_action_for(KEYS, ""), "")
        self.assertEqual(adjust_action_for({}, "wheel_up"), "")

    def test_same_key_first_match_wins(self):
        keys = {"r2_up": "f9", "r2_down": "f9"}
        self.assertEqual(adjust_action_for(keys, "f9"), "r2_up")


if __name__ == "__main__":
    unittest.main()
