"""连接页纯逻辑单元测试：不依赖网络、不依赖 Tk。"""

from __future__ import annotations

import unittest

from ps5kbm import connect_flow as flow


def credentials(**overrides) -> dict:
    """构造一份与真实 credentials.json 同构的凭据。"""
    base = {
        "device_ip": "192.168.1.38",
        "device_type": "PS5",
        "host_id": "C0151BBD7687",
        "host_name": "PS5Pro-Yi",
        "user": "paired-user",
        "profiles": {"paired-user": {"id": "57e082umn2c=", "hosts": {}}},
        "account_id_input": "57e082umn2c=",
    }
    base.update(overrides)
    return base


class SummarizeCredentialsTests(unittest.TestCase):
    def test_full_credentials(self):
        paired = flow.summarize_credentials(credentials())
        self.assertIsNotNone(paired)
        self.assertEqual(paired.host_ip, "192.168.1.38")
        self.assertEqual(paired.host_id, "C0151BBD7687")
        self.assertEqual(paired.display_name, "PS5Pro-Yi")
        self.assertEqual(paired.type_label, "PS5")
        self.assertEqual(paired.account_id, "57e082umn2c=")

    def test_missing_profiles_is_unpaired(self):
        # 没有注册档就等于没法建立会话，按未配对处理
        self.assertIsNone(flow.summarize_credentials(credentials(profiles={})))
        self.assertIsNone(flow.summarize_credentials(credentials(profiles=None)))

    def test_missing_ip_is_unpaired(self):
        self.assertIsNone(flow.summarize_credentials(credentials(device_ip="   ")))

    def test_none_and_non_dict(self):
        self.assertIsNone(flow.summarize_credentials(None))
        self.assertIsNone(flow.summarize_credentials([]))

    def test_account_id_falls_back_to_profile(self):
        paired = flow.summarize_credentials(credentials(account_id_input=""))
        self.assertEqual(paired.account_id, "57e082umn2c=")

    def test_display_name_falls_back_to_ip(self):
        paired = flow.summarize_credentials(credentials(host_name=""))
        self.assertEqual(paired.display_name, "192.168.1.38")

    def test_type_label_upper(self):
        paired = flow.summarize_credentials(credentials(device_type="ps5"))
        self.assertEqual(paired.type_label, "PS5")


class ViewSelectionTests(unittest.TestCase):
    def test_initial_view(self):
        self.assertEqual(flow.initial_view(None), flow.VIEW_FULL)
        paired = flow.summarize_credentials(credentials())
        self.assertEqual(flow.initial_view(paired), flow.VIEW_QUICK)

    def test_view_for_state(self):
        self.assertEqual(flow.view_for_state(flow.STATE_CHECKING), flow.VIEW_QUICK)
        self.assertEqual(flow.view_for_state(flow.STATE_ONLINE), flow.VIEW_QUICK)
        self.assertEqual(flow.view_for_state(flow.STATE_OFFLINE), flow.VIEW_FULL)
        self.assertEqual(flow.view_for_state(flow.STATE_ERROR), flow.VIEW_FULL)
        self.assertEqual(flow.view_for_state(flow.STATE_UNPAIRED), flow.VIEW_FULL)


class DescribeTests(unittest.TestCase):
    def setUp(self):
        self.paired = flow.summarize_credentials(credentials())

    def test_checking_disables_actions(self):
        view = flow.describe(self.paired, flow.STATE_CHECKING)
        self.assertEqual(view.tone, flow.TONE_DIM)
        self.assertFalse(view.can_connect)
        self.assertFalse(view.can_disconnect)
        self.assertFalse(view.can_recheck)

    def test_online_allows_connect(self):
        view = flow.describe(self.paired, flow.STATE_ONLINE)
        self.assertTrue(view.can_connect)
        self.assertTrue(view.can_recheck)
        self.assertFalse(view.can_disconnect)
        self.assertEqual(view.tone, flow.TONE_OK)

    def test_offline_forbids_connect(self):
        view = flow.describe(self.paired, flow.STATE_OFFLINE)
        self.assertFalse(view.can_connect)
        self.assertTrue(view.can_recheck)
        self.assertEqual(view.tone, flow.TONE_WARN)

    def test_connected_switches_buttons(self):
        view = flow.describe(
            self.paired,
            flow.STATE_ONLINE,
            connected=True,
            connected_host="192.168.1.50",
        )
        self.assertFalse(view.can_connect)
        self.assertTrue(view.can_disconnect)
        self.assertFalse(view.can_recheck)
        self.assertIn("192.168.1.50", view.status_text)

    def test_connecting_takes_priority(self):
        view = flow.describe(self.paired, flow.STATE_ONLINE, connecting=True)
        self.assertFalse(view.can_connect)
        self.assertFalse(view.can_disconnect)
        self.assertFalse(view.can_recheck)
        self.assertEqual(view.tone, flow.TONE_WARN)

    def test_probe_error(self):
        view = flow.describe(self.paired, flow.STATE_ERROR, probe_error="检测超时")
        self.assertEqual(view.tone, flow.TONE_ERR)
        self.assertIn("检测超时", view.status_text)
        self.assertFalse(view.can_connect)
        self.assertTrue(view.can_recheck)

    def test_connect_error_allows_retry(self):
        view = flow.describe(
            self.paired, flow.STATE_ONLINE, connect_error="Console is not awake"
        )
        self.assertEqual(view.tone, flow.TONE_ERR)
        self.assertTrue(view.can_connect)
        self.assertIn("Console is not awake", view.status_text)

    def test_connect_error_wins_over_probe_error(self):
        # 连接失败是用户刚做的动作，比"之前检测失败"更应该显示
        view = flow.describe(
            self.paired,
            flow.STATE_ERROR,
            probe_error="检测超时",
            connect_error="Console is not awake",
        )
        self.assertIn("连接失败", view.status_text)
        self.assertTrue(view.can_connect)

    def test_subtitle_has_ip_and_account(self):
        view = flow.describe(self.paired, flow.STATE_ONLINE)
        self.assertIn("192.168.1.38", view.subtitle)
        self.assertIn("57e082umn2c=", view.subtitle)

    def test_unpaired_placeholder(self):
        view = flow.describe(None, flow.STATE_UNPAIRED)
        self.assertEqual(view.title, "已配对主机")
        self.assertFalse(view.can_connect)


class FullNoticeTests(unittest.TestCase):
    def setUp(self):
        self.paired = flow.summarize_credentials(credentials())

    def test_no_pair_no_notice(self):
        self.assertEqual(flow.full_notice(None, flow.STATE_OFFLINE), "")

    def test_offline_notice_mentions_name_and_retry(self):
        text = flow.full_notice(self.paired, flow.STATE_OFFLINE)
        self.assertIn("PS5Pro-Yi", text)
        self.assertIn("重新检测", text)

    def test_error_notice_includes_reason(self):
        text = flow.full_notice(self.paired, flow.STATE_ERROR, probe_error="检测超时")
        self.assertIn("检测超时", text)

    def test_online_notice(self):
        text = flow.full_notice(self.paired, flow.STATE_ONLINE)
        self.assertIn("在线", text)


if __name__ == "__main__":
    unittest.main()
