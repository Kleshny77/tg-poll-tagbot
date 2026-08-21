#!/usr/bin/env python3
"""
tg-poll-tagbot — тегает участников группового чата.

Гибридная архитектура (обход ограничений Telegram):
  - bot_client  — бот из @BotFather. Интерфейс: слушает команду и шлёт теги.
  - user_client — ваша обычная user-сессия (Telethon StringSession).
                  Работает ТОЛЬКО на чтение: список участников чата и голоса.
                  Ничего не отправляет.

Почему так: Telegram запрещает бот-аккаунтам читать список проголосовавших
(messages.getPollVotes — "Only users can use this method"). Поэтому голоса и
участников читает user-аккаунт, а всё видимое в чате пишет бот.

Команды (слэш-командой или начиная с тега бота, регистр не важен):
  /tagall  (или /tegall) РЕПЛАЕМ на неанонимный опрос → тегнуть непроголосовавших;
  /tagall  (или /tegall) просто сообщением          → тегнуть всех, кроме автора;
  /tagstop @user (или /tegstop)                     → не тегать этого человека в чате;
  /tagback @user (или /tegback)                     → снова тегать.
"""

import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
from telethon.errors import (
    ChatAdminRequiredError,
    FloodWaitError,
    PollVoteRequiredError,
    RPCError,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MAX_MSG_CHARS = 3500               # запас под лимит Telegram 4096 (учитывая шапку)
FLOOD_SLEEP_THRESHOLD = 120        # авто-сон Telethon при FloodWait <= N секунд
MUTED_FILE = os.path.join(BASE_DIR, "muted.json")  # кого не тегать, по чатам

TAG_WORDS = ("tagall", "tegall")       # тегнуть всех / непроголосовавших
MUTE_WORDS = ("tagstop", "tegstop")    # исключить человека из тегания в чате
UNMUTE_WORDS = ("tagback", "tegback")  # вернуть человека в тегание
HELP_WORDS = ("help", "хелп", "помощь", "команды")  # список команд

HELP_TEXT = (
    "Команды:\n"
    "\n"
    "• /tagall реплаем на опрос — тегнуть непроголосовавших\n"
    "• /tagall без реплая или реплаем на любое сообщение — тегнуть всех (только админ)\n"
    "• /tagstop @user — не тегать этого человека в этом чате\n"
    "• /tagback @user — снова тегать\n"
    "• /help — этот список"
)

# Приветствие перед тегами непроголосовавших (реплай на опрос). Кастом-эмодзи из
# пака zmfxyq (умоляющий миньон 🥺) — сменить = другой emoji-id + запасной символ.
GREETING = (
    "прив! проголосуйте, пожалуйста "
    '<tg-emoji emoji-id="5249456539822997950">🥺</tg-emoji>'
)

# Заголовок перед тегом всех (команда без реплая): только кастом-эмодзи 🤍 из пака.
TAGALL_GREETING = '<tg-emoji emoji-id="5251293639069419539">🤍</tg-emoji>'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("tagbot")


def _require(name):
    value = os.getenv(name)
    if not value:
        sys.exit(f"[config] переменная {name} не задана в .env (см. .env.example)")
    return value


def _load_config():
    raw_id = _require("API_ID")
    try:
        api_id = int(raw_id)
    except ValueError:
        sys.exit(f"[config] API_ID должен быть числом, а не {raw_id!r}")
    return api_id, _require("API_HASH"), _require("BOT_TOKEN")


def _proxy_from_env():
    """SOCKS/HTTP-прокси из .env (для хостинга там, где MTProto режется напрямую).

    PROXY_TYPE=socks5|socks4|http, PROXY_HOST, PROXY_PORT[, PROXY_USER, PROXY_PASS].
    Пусто → None (прямое подключение). Требует python-socks.
    """
    ptype = os.getenv("PROXY_TYPE", "").strip().lower()
    if not ptype:
        return None
    host = os.getenv("PROXY_HOST", "127.0.0.1").strip()
    port = int(os.getenv("PROXY_PORT", "0") or 0)
    if not port:
        sys.exit("[config] PROXY_TYPE задан, но PROXY_PORT пуст")
    user = os.getenv("PROXY_USER") or None
    password = os.getenv("PROXY_PASS") or None
    if user and password:
        return (ptype, host, port, True, user, password)
    return (ptype, host, port)


def _load_user_session(path):
    if not os.path.exists(path):
        sys.exit(
            "[user] файл .user_session не найден — сначала выполните одноразовый "
            "вход:\n    python login_user.py"
        )
    with open(path) as fh:
        session = fh.read().strip()
    if not session:
        sys.exit("[user] файл .user_session пустой — перелогиньтесь: python login_user.py")
    return session


def _voter_id(vote):
    """id проголосовавшего из объекта голоса (совместимо со старыми/новыми слоями TL)."""
    peer = getattr(vote, "peer", None)
    if peer is not None:
        return getattr(peer, "user_id", None)
    return getattr(vote, "user_id", None)  # старые версии Telethon: MessageUserVote


def _mention(user):
    """Упоминание с пуш-уведомлением — только через @username.

    Бот не может тегнуть по id: Telethon превращает tg://user?id= в настоящее
    упоминание лишь после резолва пользователя, а бот резолвить чужих не умеет
    (тот ему не писал) — и молча выбрасывает сущность. Оставался бы голый текст
    без уведомления, поэтому таких участников выносим отдельным списком.
    """
    if getattr(user, "username", None):
        return f"@{user.username}"
    return None


def _display_name(user):
    return ((user.first_name or "") + " " + (user.last_name or "")).strip() or f"id{user.id}"


def _split_by_username(users):
    """(кого можно тегнуть с пушем, кого нельзя — без @username)."""
    taggable = [u for u in users if _mention(u)]
    nameless = [u for u in users if not _mention(u)]
    return taggable, nameless


def _pack_mentions(mentions, max_chars=MAX_MSG_CHARS):
    """Упаковать @username-упоминания в минимум сообщений под лимит длины Telegram.

    Сущности не считаем: @username сервер размечает сам, они не занимают entity.
    """
    batch, chars = [], 0
    for m in mentions:
        add = len(m) + 1  # +пробел
        if batch and chars + add > max_chars:
            yield batch
            batch, chars = [], 0
        batch.append(m)
        chars += add
    if batch:
        yield batch


def _parse_command(text, bot_mention):
    """Тип команды: 'tag' | 'mute' | 'unmute' | 'help' | None.

    Срабатывает, если ГДЕ-ТО в сообщении есть слэш-команда (/tagall, /tagstop@bot…)
    или тег бота, за которым идёт слово-команда (@bot tagall). То есть проходят и
    «текст /tagall», и «/tagall текст». Без слэша/тега (просто «tagall» в тексте) —
    не триггерит. Регистр не важен.
    """
    parts = (text or "").lower().split()
    for i, tok in enumerate(parts):
        if tok.startswith("/"):
            word = tok[1:].split("@", 1)[0]
        elif tok == bot_mention and i + 1 < len(parts):
            word = parts[i + 1]
        else:
            continue
        for kind, words in (
            ("mute", MUTE_WORDS), ("unmute", UNMUTE_WORDS),
            ("help", HELP_WORDS), ("tag", TAG_WORDS),
        ):
            if word.startswith(words):
                return kind
    return None


def _is_command_message(msg, sender_id, trigger_text):
    """Совпадает ли сообщение из истории с триггером (тот же автор и текст)."""
    return msg.sender_id == sender_id and (msg.message or "").strip() == trigger_text


def _taggable(participants, exclude_ids):
    """Кого можно тегать: без ботов, удалённых и исключённых (voters/muted/автор)."""
    return [
        u for u in participants
        if not u.bot and not getattr(u, "deleted", False) and u.id not in exclude_ids
    ]


def _can_safely_vote(poll):
    """Можно ли служебно проголосовать и потом ОТОЗВАТЬ голос.

    В quiz и в опросах с revoting_disabled Telegram запрещает отзыв
    (REVOTE_NOT_ALLOWED), в закрытых — вообще голосовать. Голосовать там нельзя:
    иначе голос читалки застрянет в чужом опросе навсегда.
    """
    return not (
        getattr(poll, "quiz", False)
        or getattr(poll, "revoting_disabled", False)
        or getattr(poll, "closed", False)
    )


def _is_admin(perms):
    """Из результата user_client.get_permissions: True для админа или создателя чата."""
    if perms is None:
        return False
    return bool(getattr(perms, "is_admin", False) or getattr(perms, "is_creator", False))


def _load_muted():
    try:
        with open(MUTED_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _muted_ids(chat_id):
    """Множество user_id, которых не тегать в этом чате."""
    return set(_load_muted().get(str(chat_id), []))


def _set_mute(chat_id, user_id, muted):
    """Добавить (muted=True) или убрать (False) user_id из списка чата."""
    data = _load_muted()
    key = str(chat_id)
    ids = set(data.get(key, []))
    ids.add(user_id) if muted else ids.discard(user_id)
    if ids:
        data[key] = sorted(ids)
    else:
        data.pop(key, None)
    with open(MUTED_FILE, "w") as fh:
        json.dump(data, fh)


async def _safe_reply(event, text, parse_mode=None):
    """Ответить в чат, не давая упасть обработчику, если сам reply не прошёл."""
    try:
        await event.reply(text, parse_mode=parse_mode)
    except Exception:
        log.exception("не удалось отправить ответ в чат")


async def _collect_voters(user_client, entity, poll_msg_id):
    """Множество user_id, проголосовавших в опросе (с пагинацией)."""
    voters = set()
    offset = None
    while True:
        res = await user_client(functions.messages.GetPollVotesRequest(
            peer=entity, id=poll_msg_id, limit=100, offset=offset,
        ))
        for vote in res.votes:
            uid = _voter_id(vote)
            if uid is not None:
                voters.add(uid)
        if not res.next_offset:
            break
        offset = res.next_offset
    return voters


async def main():
    api_id, api_hash, bot_token = _load_config()
    session_str = _load_user_session(os.path.join(BASE_DIR, ".user_session"))

    proxy = _proxy_from_env()
    if proxy:
        log.info("прокси: %s %s:%s", proxy[0], proxy[1], proxy[2])

    user_client = TelegramClient(StringSession(session_str), api_id, api_hash, proxy=proxy)
    user_client.flood_sleep_threshold = FLOOD_SLEEP_THRESHOLD
    await user_client.connect()
    if not await user_client.is_user_authorized():
        sys.exit("[user] сессия недействительна — перелогиньтесь: python login_user.py")

    bot_client = TelegramClient(
        os.path.join(BASE_DIR, ".bot_session"), api_id, api_hash, proxy=proxy,
    )
    bot_client.flood_sleep_threshold = FLOOD_SLEEP_THRESHOLD
    await bot_client.start(bot_token=bot_token)

    me_user = await user_client.get_me()
    me_bot = await bot_client.get_me()
    bot_mention = "@" + (me_bot.username or "").lower()
    reader_tag = ("@" + me_user.username) if me_user.username else (me_user.first_name or "аккаунт-читалка")

    log.info(
        "чтение: %s (id=%s) | интерфейс-бот: @%s",
        me_user.first_name, me_user.id, me_bot.username,
    )

    # Прогреваем кэш сущностей user-клиента, чтобы резолвить чаты по id.
    log.info("прогрев диалогов user-клиента…")
    async for _ in user_client.iter_dialogs():
        pass
    log.info("готов. /tagall (реплаем на опрос — непроголосовавших, иначе — всех), "
             "/tagstop @user, /tagback @user. teg-варианты тоже.")

    async def resolve_for_user(chat_id):
        try:
            return await user_client.get_entity(chat_id)
        except (ValueError, TypeError):
            async for _ in user_client.iter_dialogs():
                pass
            return await user_client.get_entity(chat_id)

    async def vote_and_collect(entity, poll_msg_id, poll):
        """Голосуем читалкой, читаем голоса, сразу отзываем свой голос.

        Telegram отдаёт список проголосовавших только тому, кто сам голосовал
        (POLL_VOTE_REQUIRED). Отзыв возвращает счётчик опроса к прежнему значению,
        так что статистика не портится. Вернёт None, если проголосовать нельзя
        (quiz, закрытый опрос, запрет переголосования).
        """
        options = [a.option for a in poll.answers]
        if not options or not _can_safely_vote(poll):
            return None
        try:
            await user_client(functions.messages.SendVoteRequest(
                peer=entity, msg_id=poll_msg_id, options=[options[0]]))
        except RPCError as exc:
            log.warning("не смог проголосовать за читалку: %s", exc)
            return None
        try:
            return await _collect_voters(user_client, entity, poll_msg_id)
        finally:
            try:
                await user_client(functions.messages.SendVoteRequest(
                    peer=entity, msg_id=poll_msg_id, options=[]))
            except RPCError as exc:
                log.warning("не смог отозвать служебный голос: %s", exc)

    async def is_sender_admin(entity, sender_id):
        """Админ ли автор команды (через аккаунт-читалку). Ошибка → False (безопаснее)."""
        try:
            return _is_admin(await user_client.get_permissions(entity, sender_id))
        except Exception:
            return False

    async def send_tags(event, chat_id, users, header):
        """Отправить упоминания users чанками, приветствие header на первом чанке."""
        reply_to = event.message.id  # ответ на команду (reply на опрос боту недоступен)
        users, nameless = _split_by_username(users)
        mentions = [_mention(u) for u in users]
        if not mentions and nameless:
            await _safe_reply(
                event,
                "Ни у кого из них нет @username — тегнуть с уведомлением не могу: "
                + ", ".join(_display_name(u) for u in nameless),
            )
            return
        total = len(mentions)
        sent = 0
        try:
            for idx, chunk in enumerate(_pack_mentions(mentions)):
                head = header + "\n" if idx == 0 else ""
                await bot_client.send_message(
                    chat_id, head + " ".join(chunk),
                    reply_to=reply_to, parse_mode="html", link_preview=False,
                )
                sent += len(chunk)
                if sent < total:
                    await asyncio.sleep(1)
        except FloodWaitError as exc:
            log.warning("FloodWait %s c — отправлено %s/%s", exc.seconds, sent, total)
            await _safe_reply(
                event,
                f"Telegram притормозил отправку (флуд-лимит {exc.seconds} c). "
                f"Успел тегнуть {sent} из {total}.",
            )
            return
        except RPCError:
            log.exception("send_message завершился ошибкой — отправлено %s/%s", sent, total)
            await _safe_reply(event, f"Не смог отправить все теги 😔 (успел {sent} из {total}).")
            return

        if nameless:
            # Честно показываем, кого не вышло тегнуть, — иначе это незаметно.
            await _safe_reply(
                event,
                "Без @username, поэтому не тегаются: "
                + ", ".join(_display_name(u) for u in nameless),
            )
        log.info("тегнул %s человек в чате %s (без @username: %s)",
                 total, chat_id, len(nameless))

    async def process_tag(event, chat_id):
        entity = await resolve_for_user(chat_id)

        # Боту Telegram не отдаёт reply-контекст, поэтому текущую команду ищем в
        # истории через user-аккаунт (самое свежее сообщение автора с этим текстом).
        trigger_text = (event.raw_text or "").strip()
        sender_id = event.sender_id
        cmd_msg = None
        async for m in user_client.iter_messages(entity, limit=50):
            if _is_command_message(m, sender_id, trigger_text):
                cmd_msg = m
                break
        if cmd_msg is None:
            await _safe_reply(event, "Не нашёл команду в чате — попробуйте ещё раз.")
            return

        muted = _muted_ids(chat_id)

        # Опрос — только если реплай именно на опрос. На любой другой реплай (или
        # без реплая) работает базовый «тег всех».
        poll = None
        if cmd_msg.reply_to_msg_id:
            replied = await user_client.get_messages(entity, ids=cmd_msg.reply_to_msg_id)
            if replied is not None and isinstance(replied.media, types.MessageMediaPoll):
                poll = replied.media.poll

        if poll is not None:
            # Реплай на опрос → тегаем непроголосовавших.
            if not poll.public_voters:
                await _safe_reply(
                    event,
                    "Опрос анонимный — Telegram не отдаёт список проголосовавших. "
                    "Работает только с открытыми (неанонимными) опросами.",
                )
                return
            try:
                voters = await _collect_voters(user_client, entity, cmd_msg.reply_to_msg_id)
            except PollVoteRequiredError:
                # Читалка ещё не голосовала — голосуем за неё и сразу отзываем голос.
                voters = await vote_and_collect(entity, cmd_msg.reply_to_msg_id, poll)
                if voters is None:
                    await _safe_reply(
                        event,
                        f"Чтобы команда сработала, в опросе должен проголосовать {reader_tag}",
                    )
                    return
                voters.discard(me_user.id)   # служебный голос не считается за настоящий
            exclude = voters | muted
            header, empty_msg = GREETING, "Все проголосовали 🎉"
        else:
            # Не опрос (или без реплая) → тегаем всех. Только для админов.
            if not await is_sender_admin(entity, sender_id):
                await _safe_reply(event, "Тегнуть всех может только админ.")
                return
            exclude = {sender_id} | muted
            header, empty_msg = TAGALL_GREETING, "Некого тегать 🎉"

        try:
            participants = await user_client.get_participants(entity)
        except ChatAdminRequiredError:
            await _safe_reply(
                event,
                "Список участников этого чата скрыт. Сделайте аккаунт-читалку "
                "администратором чата, чтобы я мог получить список участников.",
            )
            return

        targets = _taggable(participants, exclude)
        if not targets:
            await _safe_reply(event, empty_msg)
            return
        await send_tags(event, chat_id, targets, header)

    async def resolve_targets(event):
        """user_id упомянутых в сообщении (кроме самого бота): по @username и по
        text-mention (тапнутый безымянный). Возвращает {user_id: подпись}."""
        targets = {}
        raw = event.raw_text or ""
        for ent in (event.message.entities or []):
            if isinstance(ent, types.MessageEntityMentionName):
                targets[ent.user_id] = raw[ent.offset:ent.offset + ent.length] or f"id{ent.user_id}"
        for tok in raw.split():
            if tok.startswith("@") and tok.lower() != bot_mention:
                uname = tok[1:].strip(".,!?:;")
                if not uname:
                    continue
                try:
                    u = await user_client.get_entity(uname)
                    targets[u.id] = "@" + uname
                except Exception:
                    pass
        return targets

    async def process_mute(event, chat_id, mute):
        entity = await resolve_for_user(chat_id)
        if not await is_sender_admin(entity, event.sender_id):
            await _safe_reply(event, "Управлять мьютами может только админ.")
            return
        targets = await resolve_targets(event)
        if not targets:
            hint = "/tagstop @username" if mute else "/tagback @username"
            await _safe_reply(event, f"Укажи, кого — упоминанием: например {hint}")
            return
        for uid in targets:
            _set_mute(chat_id, uid, mute)
        names = ", ".join(targets.values())
        verb = "больше не тегаю" if mute else "снова тегаю"
        await _safe_reply(event, f"Ок, в этом чате {verb}: {names}")

    @bot_client.on(events.NewMessage(incoming=True))
    async def handler(event):
        if not event.is_group:
            return
        kind = _parse_command(event.raw_text or "", bot_mention)
        if kind is None:
            return
        chat_id = event.chat_id
        log.info("команда '%s' в чате %s", kind, chat_id)

        try:
            if kind == "help":
                await _safe_reply(event, HELP_TEXT)
            elif kind == "mute":
                await process_mute(event, chat_id, True)
            elif kind == "unmute":
                await process_mute(event, chat_id, False)
            else:
                await process_tag(event, chat_id)
        except FloodWaitError as exc:
            log.warning("FloodWait %s c в обработчике", exc.seconds)
            await _safe_reply(
                event,
                f"Telegram притормозил (флуд-лимит {exc.seconds} c). Попробуйте позже.",
            )
        except Exception:
            log.exception("необработанная ошибка в обработчике")
            await _safe_reply(event, "Что-то пошло не так 😔 Загляните в логи бота.")

    await bot_client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
