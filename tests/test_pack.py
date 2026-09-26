"""Тесты упаковки упоминаний в минимум сообщений под лимиты Telegram."""

import bot
from conftest import make_user


def test_pack_empty():
    assert list(bot._pack_mentions([])) == []


def test_pack_up_to_fifteen_in_one_message():
    mentions = ["@u%d" % i for i in range(15)]
    batches = list(bot._pack_mentions(mentions))
    assert len(batches) == 1
    assert batches[0] == mentions


def test_pack_sixteen_mentions_as_fifteen_plus_one():
    mentions = ["@u%d" % i for i in range(16)]
    batches = list(bot._pack_mentions(mentions))
    assert [len(batch) for batch in batches] == [15, 1]
    assert batches[0] == mentions[:15]
    assert batches[1] == mentions[15:]


def test_pack_multiple_full_mention_batches():
    mentions = ["@u%d" % i for i in range(31)]
    batches = list(bot._pack_mentions(mentions))
    assert [len(batch) for batch in batches] == [15, 15, 1]


def test_pack_keeps_all_mentions():
    mentions = ["@u%d" % i for i in range(500)]
    batches = list(bot._pack_mentions(mentions))
    flat = [m for b in batches for m in b]
    assert flat == mentions  # ничего не потеряли и порядок сохранён
    assert all(len(batch) <= bot.MAX_MENTIONS_PER_MSG for batch in batches)


def test_pack_splits_on_char_limit():
    mentions = ["@" + "x" * 100 for _ in range(100)]
    batches = list(bot._pack_mentions(mentions))
    assert len(batches) > 1
    for b in batches:
        chars = sum(len(m) + 1 for m in b)
        assert chars <= bot.MAX_MSG_CHARS or len(b) == 1


def test_pack_character_limit_can_split_before_mention_limit():
    mentions = ["@longname" for _ in range(15)]
    batches = list(bot._pack_mentions(mentions, max_chars=25))
    assert all(len(batch) <= 2 for batch in batches)
    assert [m for batch in batches for m in batch] == mentions


def test_pack_supports_smaller_custom_mention_limit():
    mentions = ["@u%d" % i for i in range(8)]
    batches = list(bot._pack_mentions(mentions, max_mentions=3))
    assert [len(batch) for batch in batches] == [3, 3, 2]


def test_pack_rejects_zero_mention_limit():
    try:
        list(bot._pack_mentions(["@alice"], max_mentions=0))
    except ValueError as exc:
        assert str(exc) == "max_mentions must be at least 1"
    else:
        raise AssertionError("zero max_mentions must be rejected")
