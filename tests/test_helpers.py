"""Юнит-тесты чистых хелперов bot.py: конфиг, сессия, прокси, голоса, упоминания."""

from types import SimpleNamespace

import pytest

import bot
from conftest import make_msg, make_user, peer_vote, user_vote


# ---------- _require / _load_config ----------

def test_require_present(monkeypatch):
    monkeypatch.setenv("SOME_VAR", "bar")
    assert bot._require("SOME_VAR") == "bar"


def test_require_missing_exits(monkeypatch):
    monkeypatch.delenv("SOME_VAR", raising=False)
    with pytest.raises(SystemExit):
        bot._require("SOME_VAR")


def test_require_empty_exits(monkeypatch):
    monkeypatch.setenv("SOME_VAR", "")
    with pytest.raises(SystemExit):
        bot._require("SOME_VAR")


def test_load_config_ok(monkeypatch):
    monkeypatch.setenv("API_ID", "42")
    monkeypatch.setenv("API_HASH", "hash")
    monkeypatch.setenv("BOT_TOKEN", "token")
    assert bot._load_config() == (42, "hash", "token")


def test_load_config_bad_api_id(monkeypatch):
    monkeypatch.setenv("API_ID", "notint")
    monkeypatch.setenv("API_HASH", "hash")
    monkeypatch.setenv("BOT_TOKEN", "token")
    with pytest.raises(SystemExit):
        bot._load_config()


def test_load_config_missing_hash(monkeypatch):
    monkeypatch.setenv("API_ID", "42")
    monkeypatch.delenv("API_HASH", raising=False)
    monkeypatch.setenv("BOT_TOKEN", "token")
    with pytest.raises(SystemExit):
        bot._load_config()


# ---------- _load_user_session ----------

def test_load_user_session_missing(tmp_path):
    with pytest.raises(SystemExit):
        bot._load_user_session(str(tmp_path / "nope"))


def test_load_user_session_empty(tmp_path):
    p = tmp_path / "s"
    p.write_text("   \n")
    with pytest.raises(SystemExit):
        bot._load_user_session(str(p))


def test_load_user_session_ok(tmp_path):
    p = tmp_path / "s"
    p.write_text("  sess123\n")
    assert bot._load_user_session(str(p)) == "sess123"


# ---------- _proxy_from_env ----------

def test_proxy_none(monkeypatch):
    monkeypatch.delenv("PROXY_TYPE", raising=False)
    assert bot._proxy_from_env() is None


def test_proxy_socks5_lowercased(monkeypatch):
    monkeypatch.setenv("PROXY_TYPE", "SOCKS5")
    monkeypatch.setenv("PROXY_HOST", "1.2.3.4")
    monkeypatch.setenv("PROXY_PORT", "1080")
    monkeypatch.delenv("PROXY_USER", raising=False)
    monkeypatch.delenv("PROXY_PASS", raising=False)
    assert bot._proxy_from_env() == ("socks5", "1.2.3.4", 1080)


def test_proxy_default_host(monkeypatch):
    monkeypatch.setenv("PROXY_TYPE", "socks5")
    monkeypatch.delenv("PROXY_HOST", raising=False)
    monkeypatch.setenv("PROXY_PORT", "10808")
    assert bot._proxy_from_env() == ("socks5", "127.0.0.1", 10808)


def test_proxy_with_auth(monkeypatch):
    monkeypatch.setenv("PROXY_TYPE", "socks5")
    monkeypatch.setenv("PROXY_HOST", "h")
    monkeypatch.setenv("PROXY_PORT", "9")
    monkeypatch.setenv("PROXY_USER", "u")
    monkeypatch.setenv("PROXY_PASS", "p")
    assert bot._proxy_from_env() == ("socks5", "h", 9, True, "u", "p")


def test_proxy_missing_port_exits(monkeypatch):
    monkeypatch.setenv("PROXY_TYPE", "socks5")
    monkeypatch.delenv("PROXY_PORT", raising=False)
    with pytest.raises(SystemExit):
        bot._proxy_from_env()


# ---------- _voter_id ----------

def test_voter_id_peer():
    assert bot._voter_id(peer_vote(5)) == 5


def test_voter_id_old_style():
    assert bot._voter_id(user_vote(7)) == 7


def test_voter_id_peer_none():
    assert bot._voter_id(SimpleNamespace(peer=SimpleNamespace(user_id=None))) is None


def test_voter_id_nothing():
    assert bot._voter_id(SimpleNamespace()) is None


# ---------- _mention ----------

def test_mention_username():
    assert bot._mention(make_user(1, username="alice")) == "@alice"


def test_mention_none_without_username():
    # бот не может тегнуть по id — такие идут отдельным списком
    assert bot._mention(make_user(42, first_name="Bob", last_name="Li")) is None


def test_display_name_full():
    assert bot._display_name(make_user(42, first_name="Bob", last_name="Li")) == "Bob Li"


def test_display_name_first_only():
    assert bot._display_name(make_user(7, first_name="Ann")) == "Ann"


def test_display_name_fallback_to_id():
    assert bot._display_name(make_user(9)) == "id9"


def test_split_by_username():
    users = [
        make_user(1, username="alice"),
        make_user(2, first_name="Bob"),
        make_user(3, username="carol"),
    ]
    taggable, nameless = bot._split_by_username(users)
    assert [u.id for u in taggable] == [1, 3]
    assert [u.id for u in nameless] == [2]


def test_split_all_taggable():
    users = [make_user(1, username="a"), make_user(2, username="b")]
    taggable, nameless = bot._split_by_username(users)
    assert len(taggable) == 2 and nameless == []


# ---------- _is_command_message ----------

def test_is_command_message_match():
    assert bot._is_command_message(make_msg(1, "/tagall"), 1, "/tagall")


def test_is_command_message_strips_whitespace():
    assert bot._is_command_message(make_msg(1, "/tagall  "), 1, "/tagall")


def test_is_command_message_wrong_sender():
    assert not bot._is_command_message(make_msg(2, "/tagall"), 1, "/tagall")


def test_is_command_message_wrong_text():
    assert not bot._is_command_message(make_msg(1, "/tegall"), 1, "/tagall")


def test_is_command_message_none_text():
    assert not bot._is_command_message(make_msg(1, None), 1, "/tagall")


# ---------- _taggable ----------

def test_taggable_filters_all_cases():
    ppl = [
        make_user(1, first_name="A"),                  # не исключён -> в списке
        make_user(2, first_name="Excl"),               # исключён -> нет
        make_user(3, first_name="Botik", bot=True),    # бот -> нет
        make_user(4, first_name="Del", deleted=True),  # удалён -> нет
        make_user(5, first_name="B"),                  # не исключён -> в списке
    ]
    assert [u.id for u in bot._taggable(ppl, {2})] == [1, 5]


def test_taggable_all_excluded():
    assert bot._taggable([make_user(1), make_user(2)], {1, 2}) == []


def test_taggable_preserves_order():
    ppl = [make_user(30), make_user(10), make_user(20)]
    assert [u.id for u in bot._taggable(ppl, set())] == [30, 10, 20]


# ---------- _can_safely_vote ----------

def _poll(**flags):
    base = dict(quiz=False, revoting_disabled=False, closed=False)
    base.update(flags)
    return SimpleNamespace(**base)


def test_can_vote_in_regular_poll():
    assert bot._can_safely_vote(_poll())


def test_cannot_vote_in_quiz():
    # в quiz голос не отозвать — служебный голос застрял бы навсегда
    assert not bot._can_safely_vote(_poll(quiz=True))


def test_cannot_vote_when_revoting_disabled():
    assert not bot._can_safely_vote(_poll(revoting_disabled=True))


def test_cannot_vote_in_closed_poll():
    assert not bot._can_safely_vote(_poll(closed=True))


def test_can_vote_when_flags_absent():
    # у старых слоёв TL флагов может не быть вовсе
    assert bot._can_safely_vote(SimpleNamespace())


# ---------- _is_admin ----------

def test_is_admin_true_for_admin():
    assert bot._is_admin(SimpleNamespace(is_admin=True, is_creator=False))


def test_is_admin_true_for_creator():
    assert bot._is_admin(SimpleNamespace(is_admin=False, is_creator=True))


def test_is_admin_false_for_regular():
    assert not bot._is_admin(SimpleNamespace(is_admin=False, is_creator=False))


def test_is_admin_none():
    assert not bot._is_admin(None)
