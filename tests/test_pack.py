"""Тесты упаковки упоминаний в минимум сообщений под лимиты Telegram."""

import bot
from conftest import make_user


def test_pack_empty():
    assert list(bot._pack_mentions([])) == []


def test_pack_small_group_one_message():
    mentions = ["@u%d" % i for i in range(60)]
    batches = list(bot._pack_mentions(mentions))
    assert len(batches) == 1
    assert batches[0] == mentions


def test_pack_keeps_all_mentions():
    mentions = ["@u%d" % i for i in range(500)]
    batches = list(bot._pack_mentions(mentions))
    flat = [m for b in batches for m in b]
    assert flat == mentions  # ничего не потеряли и порядок сохранён


def test_pack_splits_on_char_limit():
    mentions = ["@" + "x" * 100 for _ in range(100)]
    batches = list(bot._pack_mentions(mentions))
    assert len(batches) > 1
    for b in batches:
        chars = sum(len(m) + 1 for m in b)
        assert chars <= bot.MAX_MSG_CHARS or len(b) == 1


def test_pack_usernames_dont_hit_entity_limit():
    # 300 @username (0 сущностей) должны уложиться в одно сообщение (char-limited)
    mentions = ["@u%d" % i for i in range(300)]
    batches = list(bot._pack_mentions(mentions))
    assert len(batches) == 1
