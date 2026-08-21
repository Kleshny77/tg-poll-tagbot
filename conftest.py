"""Общие заглушки и фабрики для тестов tg-poll-tagbot.

Лежит в корне проекта, поэтому pytest добавляет корень в sys.path — тесты могут
`import bot` / `import login_qr` и `from conftest import ...`.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))


def make_user(id, username=None, first_name=None, last_name=None, bot=False, deleted=False):
    """Похожий на telethon User объект для _mention / _non_voters."""
    return SimpleNamespace(
        id=id, username=username, first_name=first_name, last_name=last_name,
        bot=bot, deleted=deleted,
    )


def make_msg(sender_id, message, reply_to_msg_id=None):
    """Похожее на telethon Message сообщение из истории для _is_command_message."""
    return SimpleNamespace(
        sender_id=sender_id, message=message, reply_to_msg_id=reply_to_msg_id,
    )


def peer_vote(user_id):
    """Новый слой TL: MessagePeerVote с .peer.user_id."""
    return SimpleNamespace(peer=SimpleNamespace(user_id=user_id))


def user_vote(user_id):
    """Старый слой TL: MessageUserVote с .user_id (без .peer)."""
    return SimpleNamespace(user_id=user_id)


def votes_page(votes, next_offset=None):
    """Похожая на messages.VotesList страница ответа GetPollVotes."""
    return SimpleNamespace(votes=list(votes), next_offset=next_offset)


class FakeVotesClient:
    """Callable-заглушка user_client: _collect_voters делает await client(request).

    Отдаёт заранее заданные страницы по очереди; считает число вызовов.
    """

    def __init__(self, pages):
        self._pages = list(pages)
        self.calls = 0

    async def __call__(self, request):
        page = self._pages[self.calls]
        self.calls += 1
        return page


class FakeEvent:
    """Заглушка события Telethon: копит reply-вызовы, опционально падает на reply."""

    def __init__(self, raise_on_reply=False):
        self.replies = []
        self._raise = raise_on_reply

    async def reply(self, text, parse_mode=None):
        if self._raise:
            raise RuntimeError("reply failed")
        self.replies.append((text, parse_mode))
