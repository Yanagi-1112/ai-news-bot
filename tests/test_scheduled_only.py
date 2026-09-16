from datetime import datetime
from types import SimpleNamespace

import httpx
from freezegun import freeze_time

from bot.config import Settings
from bot.poster import Poster
from bot.scheduler import JST, NewsScheduler
from bot.store import Store


def test_scheduled_only_retains_articles_and_slots_across_restart(tmp_path):
    path = tmp_path / 'news.sqlite3'
    start = datetime(2026, 9, 17, 8, tzinfo=JST)
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200, json={'id': 'delivered'})
    ))
    settings = Settings('', 'stub', 'stub', 'stub', data_dir=tmp_path)

    def runtime(store):
        poster = Poster(store, '', client, additional_webhook_urls=['https://example.com/automata'],
                        additional_start_at=start)
        return NewsScheduler(store, SimpleNamespace(collect=lambda sources: []),
                             SimpleNamespace(curate=lambda rows: None), poster, settings, [])

    store = Store(path)
    store.mark_initialized()
    keys = []
    for title, breaking in [('Breaking release', True), ('Daily digest', False)]:
        key = store.add_article({'url': 'https://example.com/' + str(breaking), 'title': title,
                                'source_id': 'test', 'source_category': 'official',
                                'published_at': '2026-09-16T09:00:00+09:00'})
        store.update_article(key, state='scored', score=95 if breaking else 80, breaking=int(breaking))
        keys.append(key)
    with freeze_time('2026-09-16T20:00:00+09:00'):
        runtime(store).tick()
        assert not calls
        assert all(store.get_article(key)['state'] == 'scored' for key in keys)
        assert store.conn.execute('SELECT count(*) FROM delivery_slots').fetchone()[0] == 0
    store.close()
    store = Store(path)
    with freeze_time('2026-09-17T07:59:59+09:00'):
        runtime(store).tick()
        assert not calls
    with freeze_time('2026-09-17T08:00:00+09:00'):
        runtime(store).tick()
        assert len(calls) == 2
        assert all(request.url.path == '/automata' for request in calls)
        assert all(store.get_article(key)['state'] == 'sent' for key in keys)
    store.close()
    store = Store(path)
    with freeze_time('2026-09-17T08:30:00+09:00'):
        runtime(store).tick()
        assert len(calls) == 2
    store.close()


def test_send_test_reports_no_delivery_before_start():
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: calls.append(request) or httpx.Response(200)
    ))
    store = Store()
    poster = Poster(store, '', client, additional_webhook_urls=['https://example.com/automata'],
                    additional_start_at=datetime(2026, 9, 17, 8, tzinfo=JST))
    with freeze_time('2026-09-17T07:59:59+09:00'):
        assert poster.send_test() is False
        assert not calls
    store.close()
