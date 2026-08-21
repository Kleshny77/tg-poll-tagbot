"""Тесты мьютов: персистентность в muted.json, изоляция по чатам, снятие."""

import json

import bot


def test_muted_ids_empty_when_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "MUTED_FILE", str(tmp_path / "m.json"))
    assert bot._muted_ids(123) == set()


def test_load_muted_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "MUTED_FILE", str(tmp_path / "nope.json"))
    assert bot._load_muted() == {}


def test_set_and_get_mute(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "MUTED_FILE", str(tmp_path / "m.json"))
    bot._set_mute(123, 5, True)
    bot._set_mute(123, 7, True)
    assert bot._muted_ids(123) == {5, 7}


def test_mute_isolated_per_chat(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "MUTED_FILE", str(tmp_path / "m.json"))
    bot._set_mute(1, 5, True)
    bot._set_mute(2, 6, True)
    assert bot._muted_ids(1) == {5}
    assert bot._muted_ids(2) == {6}
    assert bot._muted_ids(999) == set()


def test_unmute_removes_and_prunes_empty_chat(monkeypatch, tmp_path):
    f = tmp_path / "m.json"
    monkeypatch.setattr(bot, "MUTED_FILE", str(f))
    bot._set_mute(1, 10, True)
    bot._set_mute(1, 10, False)
    assert bot._muted_ids(1) == set()
    # пустой чат убирается из файла целиком
    assert json.loads(f.read_text()) == {}


def test_unmute_keeps_other_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "MUTED_FILE", str(tmp_path / "m.json"))
    bot._set_mute(1, 10, True)
    bot._set_mute(1, 20, True)
    bot._set_mute(1, 10, False)
    assert bot._muted_ids(1) == {20}


def test_double_mute_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "MUTED_FILE", str(tmp_path / "m.json"))
    bot._set_mute(1, 10, True)
    bot._set_mute(1, 10, True)
    assert bot._muted_ids(1) == {10}


def test_unmute_absent_is_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "MUTED_FILE", str(tmp_path / "m.json"))
    bot._set_mute(1, 10, False)  # снимаем того, кого нет
    assert bot._muted_ids(1) == set()
