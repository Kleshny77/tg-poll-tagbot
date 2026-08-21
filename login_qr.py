#!/usr/bin/env python3
"""
QR-вход в user-сессию для tg-poll-tagbot.

Вы сканируете QR-код телефоном (Telegram → Настройки → Устройства →
«Подключить устройство»/«Link Desktop Device»). Ни код, ни пароль руками
не вводятся через посредника. По успеху строка сессии сохраняется в .user_session.

Два режима:
  • Терминал (интерактивно): QR рисуется прямо в консоли; если включён облачный
    пароль (2FA) — скрипт скрытым вводом спросит его у вас. Запуск:
        venv/bin/python login_qr.py
  • Headless (запуск не в TTY, для оркестрации): пишет QR в .login_qr.svg и
    печатает строки-маркеры QR_URL / QR_SVG / USER_OK / NEED_2FA / ALREADY_AUTH.
"""

import asyncio
import getpass
import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError
import qrcode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
SESSION_FILE = os.path.join(BASE_DIR, ".user_session")
QR_SVG = os.path.join(BASE_DIR, ".login_qr.svg")


def _require(name):
    value = os.getenv(name)
    if not value:
        sys.exit(f"[config] переменная {name} не задана в .env")
    return value


def _write_qr_svg(url, box=10, border=4):
    """QR как самодостаточный SVG с белым фоном (сканируется на любой теме)."""
    qr = qrcode.QRCode(border=border, box_size=box)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    size = n * box
    rects = [
        f'<rect x="{x * box}" y="{y * box}" width="{box}" height="{box}"/>'
        for y, row in enumerate(matrix)
        for x, cell in enumerate(row)
        if cell
    ]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}">'
        f'<rect width="{size}" height="{size}" fill="#ffffff"/>'
        f'<g fill="#000000">{"".join(rects)}</g></svg>'
    )
    with open(QR_SVG, "w") as fh:
        fh.write(svg)


def _emit_marker_qr(url):
    _write_qr_svg(url)
    print("QR_URL " + url, flush=True)
    print("QR_SVG " + QR_SVG, flush=True)


def _print_ascii_qr(url):
    qr = qrcode.QRCode()
    qr.add_data(url)
    qr.make(fit=True)
    sys.stdout.write("\033[2J\033[H")  # очистить экран
    print("Отсканируйте QR телефоном:")
    print("Telegram → Настройки → Устройства → Подключить устройство\n")
    qr.print_ascii(invert=True)
    print("\n(код обновляется автоматически; ждём скан…)", flush=True)


def _save_session(session_str):
    fd = os.open(SESSION_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(session_str)


async def _login_terminal(client):
    qr_login = await client.qr_login()
    while True:
        _print_ascii_qr(qr_login.url)
        try:
            await qr_login.wait(timeout=25)
            return 0
        except asyncio.TimeoutError:
            await qr_login.recreate()
        except SessionPasswordNeededError:
            print("\nУ аккаунта включён облачный пароль двухэтапной аутентификации.")
            print("Это пароль из Telegram → Настройки → Конфиденциальность →")
            print("Двухэтапная аутентификация (НЕ код-пароль для входа в приложение).")
            for _ in range(3):
                password = getpass.getpass("Введите пароль 2FA (ввод скрыт): ")
                try:
                    await client.sign_in(password=password)
                    return 0
                except PasswordHashInvalidError:
                    print("Неверный пароль, попробуйте ещё раз.")
            print("Три неверных попытки. Запустите команду заново.")
            return 3


async def _login_headless(client):
    qr_login = await client.qr_login()
    _emit_marker_qr(qr_login.url)
    while True:
        try:
            await qr_login.wait(timeout=25)
            return 0
        except asyncio.TimeoutError:
            await qr_login.recreate()
            _emit_marker_qr(qr_login.url)
        except SessionPasswordNeededError:
            print("NEED_2FA", flush=True)
            return 2


async def run():
    api_id = int(_require("API_ID"))
    api_hash = _require("API_HASH")
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            login = _login_terminal if interactive else _login_headless
            rc = await login(client)
            if rc != 0:
                return rc
        elif not interactive:
            print("ALREADY_AUTH", flush=True)

        _save_session(client.session.save())
        me = await client.get_me()
        if interactive:
            print(f"\nГотово! Вошли как {me.first_name} (id={me.id}). Сессия сохранена.")
            print("Теперь запустите бота:  ./run.sh")
        else:
            print(
                "USER_OK id=%s name=%s username=@%s"
                % (me.id, me.first_name, me.username),
                flush=True,
            )
        try:
            os.remove(QR_SVG)
        except OSError:
            pass
        return 0
    finally:
        await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
