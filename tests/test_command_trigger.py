"""Тесты _parse_command: тип команды (tag/mute/unmute) по слэшу или тегу бота."""

import pytest

import bot

BOT_MENTION = "@miniontegbot"

TAG = [
    "/tagall",
    "/tegall",
    "/TagAll",                    # регистр не важен
    "/tagallопрос",               # слитно с текстом
    "/tagall@minionTegBot",       # /cmd@botname
    "/tegall@minionTegBot",
    "/tagall всех отметь",        # команда + текст
    "fasdfasd /tagall",           # текст + команда
    "text /tagall in middle",     # команда в середине
    "@minionTegBot tagall",       # тег бота + команда
    "@miniontegbot tegallвсе",
    "привет @minionTegBot tagall",  # текст + тег бота + команда
]

MUTE = [
    "/tagstop @u",
    "/tegstop @u",
    "/tagstop@minionTegBot @u",
    "@minionTegBot tagstop @u",
    "/TagStop @u",
]

UNMUTE = [
    "/tagback @u",
    "/tegback @u",
    "@minionTegBot tagback @u",
]

HELP = [
    "/help",
    "/Help",
    "/help@minionTegBot",
    "@minionTegBot help",
    "/помощь",
    "/команды",
    "/хелп",
]

NONE = [
    "tagall",                     # без слэша/тега
    "tagAll",
    "я против tagall",            # слово без слэша/тега — не команда
    "@minionTegBot привет",       # тег без команды
    "@minionTegBot",              # только тег
    "@otherbot tagall",           # чужой бот
    "/teg",                       # обрывок
    "/tag",
    "tag",
    "привет",
    "",
    "   ",
    "/",
]


@pytest.mark.parametrize("text", TAG)
def test_tag(text):
    assert bot._parse_command(text, BOT_MENTION) == "tag"


@pytest.mark.parametrize("text", MUTE)
def test_mute(text):
    assert bot._parse_command(text, BOT_MENTION) == "mute"


@pytest.mark.parametrize("text", UNMUTE)
def test_unmute(text):
    assert bot._parse_command(text, BOT_MENTION) == "unmute"


@pytest.mark.parametrize("text", HELP)
def test_help(text):
    assert bot._parse_command(text, BOT_MENTION) == "help"


# "/tagstop" без цели всё равно распознаётся как mute (цель проверяется в обработчике)
def test_mute_without_target_is_mute():
    assert bot._parse_command("/tagstop", BOT_MENTION) == "mute"


@pytest.mark.parametrize("text", NONE)
def test_none(text):
    assert bot._parse_command(text, BOT_MENTION) is None
