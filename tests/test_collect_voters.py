"""Тесты _collect_voters: пагинация, дедуп, старый/новый слой голосов."""

from types import SimpleNamespace

import bot
from conftest import FakeVotesClient, peer_vote, user_vote, votes_page


async def test_single_page():
    client = FakeVotesClient([votes_page([peer_vote(1), peer_vote(2)])])
    assert await bot._collect_voters(client, "entity", 10) == {1, 2}
    assert client.calls == 1


async def test_paginated_and_dedup():
    client = FakeVotesClient([
        votes_page([peer_vote(1), peer_vote(2)], next_offset="p2"),
        votes_page([peer_vote(3), peer_vote(2)], next_offset=None),
    ])
    assert await bot._collect_voters(client, "e", 10) == {1, 2, 3}
    assert client.calls == 2


async def test_mixed_old_and_new_style():
    client = FakeVotesClient([votes_page([peer_vote(1), user_vote(9)])])
    assert await bot._collect_voters(client, "e", 1) == {1, 9}


async def test_empty():
    client = FakeVotesClient([votes_page([])])
    assert await bot._collect_voters(client, "e", 1) == set()


async def test_skips_none_ids():
    bad = SimpleNamespace(peer=SimpleNamespace(user_id=None))
    client = FakeVotesClient([votes_page([bad, peer_vote(5)])])
    assert await bot._collect_voters(client, "e", 1) == {5}


async def test_stops_on_empty_next_offset_across_pages():
    # next_offset="" (пусто) должен остановить пагинацию, как и None
    client = FakeVotesClient([votes_page([peer_vote(1)], next_offset="")])
    assert await bot._collect_voters(client, "e", 1) == {1}
    assert client.calls == 1
