#!/usr/bin/env python3
"""
Одноразовый вход в user-аккаунт для tg-poll-tagbot.

Запускается один раз. Спросит номер телефона, затем код из Telegram
(и пароль двухфакторки, если включена). Сохранит строку сессии в
файл .user_session — дальше bot.py работает без каких-либо подтверждений.

Сессию можно в любой момент отозвать в Telegram:
  Настройки → Устройства → выбрать сессию → Завершить.
"""

import os
import sys

from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
SESSION_FILE = os.path.join(BASE_DIR, ".user_session")


def _require(name):
    value = os.getenv(name)
    if not value:
        sys.exit(f"[config] переменная {name} не задана в .env (см. .env.example)")
    return value


def main():
    raw_id = _require("API_ID")
    try:
        api_id = int(raw_id)
    except ValueError:
        sys.exit(f"[config] API_ID должен быть числом, а не {raw_id!r}")
    api_hash = _require("API_HASH")

    if os.path.exists(SESSION_FILE):
        answer = input(".user_session уже существует. Перелогиниться заново? [y/N] ")
        if answer.strip().lower() not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return

    print("Входим в user-аккаунт (этот аккаунт будет читать участников и голоса).")
    with TelegramClient(StringSession(), api_id, api_hash) as client:
        session_str = client.session.save()
        me = client.get_me()
        # Создаём файл сразу с правами 0600 (строка сессии = полный доступ
        # к аккаунту), без окна, где он world-readable до chmod.
        fd = os.open(SESSION_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(session_str)
        print(f"\nГотово. Вошли как: {me.first_name} (id={me.id})")
        print(f"Сессия сохранена в {SESSION_FILE} (chmod 600).")
        print("Теперь можно запускать бота: ./run.sh")


if __name__ == "__main__":
    main()
