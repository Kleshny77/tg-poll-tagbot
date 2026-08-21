"""Тесты форматирования: кастом-эмодзи в GREETING/REPLY_HINT и упоминания вместе."""

from telethon.extensions import html
from telethon.tl.types import MessageEntityCustomEmoji, MessageEntityTextUrl

import bot
from conftest import make_user


def test_greeting_custom_emoji():
    text, ents = html.parse(bot.GREETING)
    assert text == "прив! проголосуйте, пожалуйста 🥺"
    custom = [e for e in ents if isinstance(e, MessageEntityCustomEmoji)]
    assert len(custom) == 1
    assert custom[0].document_id == 5249456539822997950


def test_tagall_greeting_is_only_custom_emoji():
    text, ents = html.parse(bot.TAGALL_GREETING)
    assert text == "🤍"          # только эмодзи, без текста
    custom = [e for e in ents if isinstance(e, MessageEntityCustomEmoji)]
    assert len(custom) == 1
    assert custom[0].document_id == 5251293639069419539


def test_full_tag_message_has_emoji_and_mentions():
    taggable, nameless = bot._split_by_username([
        make_user(1, username="alice"),
        make_user(2, first_name="Bob"),
    ])
    mentions = " ".join(bot._mention(u) for u in taggable)
    text, ents = html.parse(bot.GREETING + "\n" + mentions)
    assert any(isinstance(e, MessageEntityCustomEmoji) for e in ents)
    # ссылок tg://user?id= больше нет: бот не может тегнуть по id, они молча терялись
    assert not any(isinstance(e, MessageEntityTextUrl) for e in ents)
    assert "@alice" in text
    assert [u.id for u in nameless] == [2]
