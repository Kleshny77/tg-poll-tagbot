"""Тесты _safe_reply: передаёт parse_mode и не роняет обработчик при ошибке."""

import bot
from conftest import FakeEvent


async def test_records_with_parse_mode():
    ev = FakeEvent()
    await bot._safe_reply(ev, "hi", parse_mode="html")
    assert ev.replies == [("hi", "html")]


async def test_default_parse_mode_none():
    ev = FakeEvent()
    await bot._safe_reply(ev, "hi")
    assert ev.replies == [("hi", None)]


async def test_swallows_errors():
    ev = FakeEvent(raise_on_reply=True)
    await bot._safe_reply(ev, "hi")  # не должно бросить исключение
    assert ev.replies == []
