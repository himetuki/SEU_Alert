"""预筛链测试：发送者过滤 / 去重 / 关键词 / at_all / dry_run / **顺序回归（ADR-008）**。"""

from __future__ import annotations

from qq_relay.contracts import RawEvent
from qq_relay.pipeline.prefilter import Deduper, Prefilter, Stage

NOTICE = "高等数学第五章习题册作业已发布，11月15日23:59前提交至学习通"
CHATTER = "哈哈今天天气真不错啊大家辛苦了"


def _ev(group: str, text: str, sender: str = "10001", at_all: bool = False) -> RawEvent:
    return RawEvent("qq_group", group, f"群{group}", sender, "某人", "m1", text, 1, at_all)


class TestSenderFilter:
    def test_off_passes(self, groups_cfg):
        pf = Prefilter()
        d = pf.process(_ev("111", NOTICE), groups_cfg.profile_of("111"), Deduper())
        assert d.passed and d.stage is Stage.PASS

    def test_blacklist_drops(self, groups_cfg):
        pf = Prefilter()
        d = pf.process(_ev("333", NOTICE, sender="999"), groups_cfg.profile_of("333"), Deduper())
        assert not d.passed and d.stage is Stage.SENDER_FILTER
        assert "黑名单" in d.reason

    def test_dry_run_passes_with_flag(self, groups_cfg):
        pf = Prefilter()
        d = pf.process(_ev("444", NOTICE, sender="999"), groups_cfg.profile_of("444"), Deduper())
        assert d.passed and d.dry_run_would_drop and d.stage is Stage.SENDER_FILTER

    def test_whitelist_miss_drops(self, groups_yaml_path):
        from qq_relay.config import load_groups

        text = groups_yaml_path.read_text(encoding="utf-8").replace(
            'sender_filter: { mode: blacklist, blacklist: ["999"], roles: { allow: [], deny: [] }, dry_run: true, log_filtered: true }',
            'sender_filter: { mode: whitelist, whitelist: ["10001"], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }',
        )
        groups_yaml_path.write_text(text, encoding="utf-8")
        cfg = load_groups(groups_yaml_path)
        d = Prefilter().process(_ev("444", NOTICE, sender="777"),
                                cfg.profile_of("444"), Deduper())
        assert not d.passed and "白名单" in d.reason


class TestDedup:
    def test_duplicate_detected(self, groups_cfg):
        pf, dd = Prefilter(), Deduper()
        d1 = pf.process(_ev("111", NOTICE), groups_cfg.profile_of("111"), dd)
        assert d1.passed
        dd.register(d1.content_hash, "evt-1")
        d2 = pf.process(_ev("222", NOTICE), groups_cfg.profile_of("222"), dd)
        assert not d2.passed and d2.stage is Stage.DEDUP and d2.duplicate_of == "evt-1"

    def test_content_key_ignores_whitespace(self):
        a, b = _ev("111", "作业 周五 交"), _ev("222", "作业周五交")
        assert a.content_key() == b.content_key()


class TestKeyword:
    def test_profile_word_hits(self, groups_cfg):
        d = Prefilter().process(_ev("222", "数学建模竞赛开始报名了"),
                                groups_cfg.profile_of("222"), Deduper())
        assert d.passed and "竞赛" in d.matched

    def test_generic_word_hits(self, groups_cfg):
        d = Prefilter().process(_ev("111", "请大家注意一下"), groups_cfg.profile_of("111"), Deduper())
        assert d.passed and "请" in d.matched

    def test_miss_drops(self, groups_cfg):
        d = Prefilter().process(_ev("111", CHATTER), groups_cfg.profile_of("111"), Deduper())
        assert not d.passed and d.stage is Stage.KEYWORD

    def test_at_all_passes_without_keyword(self, groups_cfg):
        d = Prefilter().process(_ev("111", CHATTER, at_all=True),
                                groups_cfg.profile_of("111"), Deduper())
        assert d.passed


class TestOrderRegressionADR008:
    """顺序回归：被发送者过滤丢掉的拷贝，不得把 hash 登记进去重库。

    反序实现（先去重后过滤）会让 B 群同内容拷贝被误判"已见过"——静默漏报。
    """

    def test_filtered_copy_does_not_poison_dedup(self, groups_cfg):
        pf, dd = Prefilter(), Deduper()
        # A 群（333）黑名单发送者的拷贝：被发送者过滤丢弃，不登记 hash
        d1 = pf.process(_ev("333", NOTICE, sender="999"), groups_cfg.profile_of("333"), dd)
        assert not d1.passed and d1.stage is Stage.SENDER_FILTER
        # B 群（222）同内容拷贝：必须能通过（而不是被判重跳过）
        d2 = pf.process(_ev("222", NOTICE, sender="20002"), groups_cfg.profile_of("222"), dd)
        assert d2.passed and d2.stage is Stage.PASS

    def test_passed_copy_does_register_for_fan_in(self, groups_cfg):
        pf, dd = Prefilter(), Deduper()
        d1 = pf.process(_ev("111", NOTICE), groups_cfg.profile_of("111"), dd)
        dd.register(d1.content_hash, "evt-1")
        d2 = pf.process(_ev("222", NOTICE), groups_cfg.profile_of("222"), dd)
        assert d2.stage is Stage.DEDUP and d2.duplicate_of == "evt-1"
