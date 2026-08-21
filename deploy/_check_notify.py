#!/usr/bin/env python3
"""Диагностика: настройки уведомлений — глобальные, по чату с ботом, по группам."""

import asyncio
import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient, functions, types
from telethon.sessions import StringSession

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, "..", ".env"))
api_id = int(os.environ["API_ID"])
api_hash = os.environ["API_HASH"]
with open(os.path.join(BASE, "..", ".user_session")) as fh:
    session = fh.read().strip()

proxy = None
if os.getenv("PROXY_TYPE"):
    proxy = (os.getenv("PROXY_TYPE"), os.getenv("PROXY_HOST", "127.0.0.1"),
             int(os.getenv("PROXY_PORT", "10808")))

BOT_USERNAME = "minionTegBot"


def describe(label, s):
    mute = getattr(s, "mute_until", None)
    silent = getattr(s, "silent", None)
    sound = getattr(s, "other_sound", None) or getattr(s, "ios_sound", None)
    print(f"  {label}: mute_until={mute} silent={silent} sound={type(sound).__name__ if sound else None}")


async def main():
    client = TelegramClient(StringSession(session), api_id, api_hash, proxy=proxy)
    await client.connect()

    print("=== ГЛОБАЛЬНЫЕ настройки ===")
    for label, peer in (
        ("личные чаты (сюда попадает бот)", types.InputNotifyUsers()),
        ("группы", types.InputNotifyChats()),
        ("каналы", types.InputNotifyBroadcasts()),
    ):
        describe(label, await client(functions.account.GetNotifySettingsRequest(peer=peer)))

    print("=== ЧАТ С БОТОМ ===")
    try:
        bot_entity = await client.get_entity(BOT_USERNAME)
        s = await client(functions.account.GetNotifySettingsRequest(
            peer=types.InputNotifyPeer(await client.get_input_entity(bot_entity))))
        describe(f"@{BOT_USERNAME}", s)
    except Exception as exc:
        print("  не смог получить:", exc)

    print("=== ГРУППЫ, ГДЕ РАБОТАЛ БОТ (первые 6) ===")
    shown = 0
    async for dialog in client.iter_dialogs():
        if not dialog.is_group or shown >= 6:
            continue
        s = await client(functions.account.GetNotifySettingsRequest(
            peer=types.InputNotifyPeer(await client.get_input_entity(dialog.entity))))
        describe(f"«{dialog.name}»", s)
        shown += 1

    await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
