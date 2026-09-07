from datetime import datetime, date, timedelta
from dataclasses import replace
from types import SimpleNamespace
import json

import httpx
import pytest

from bot.config import Settings
from bot.curator import Curator
from bot.poster import Poster
from bot.scheduler import NewsScheduler, JST
from bot.store import Store

NOW = datetime(2026, 9, 8, 8, tzinfo=JST)


def article(store, title, *, score=80, breaking=False, published=None, seen=None, state='scored'):
    key = store.add_article({'url': 'https://example.com/' + title, 'title': title,
                            'source_id': 'official', 'source_category': 'official',
                            'published_at': published, 'first_seen_at': seen or NOW.isoformat()})
    store.update_article(key, state=state, score=score, breaking=int(breaking), headline_ja=title, summary_ja='短い要約')
    return key


def runtime(store, tmp_path, handler):
    collector = SimpleNamespace(collect=lambda sources: [])
    curator = SimpleNamespace(curate=lambda rows: None)
    settings = Settings('https://discord.example/hook', 'stub', 'stub', 'stub', data_dir=tmp_path)
    poster = Poster(store, settings.discord_webhook_url, httpx.Client(transport=httpx.MockTransport(handler)))
    return NewsScheduler(store, collector, curator, poster, settings, [])


@pytest.mark.parametrize('published,seen,breaking,score', [
    ('2026-08-01T10:00:00Z', None, True, 99),
    ('Mon, 01 Jun 2026 10:00:00 GMT', None, True, 99),
    (None, '2026-09-01T10:00:00Z', True, 99),
    (None, None, False, 99),
    (None, None, True, 40),
])
def test_stale_or_non_breaking_articles_never_trigger_alert(tmp_path, published, seen, breaking, score):
    store = Store()
    article(store, 'candidate', score=score, breaking=breaking, published=published, seen=seen)
    calls = []
    app = runtime(store, tmp_path, lambda req: calls.append(req) or httpx.Response(200, json={'id':'m'}))
    app.tick(NOW - timedelta(hours=1))
    assert not calls


def test_digest_excludes_low_scores_and_stale_new_articles_before_llm(tmp_path):
    store = Store()
    low = article(store, 'funding', score=15)
    good = article(store, 'new-model', score=80)
    old = article(store, 'old-release', state='new', published='2020-01-01T00:00:00Z')
    calls, curated = [], []
    app = runtime(store, tmp_path, lambda req: calls.append(req) or httpx.Response(200, json={'id':'m'}))
    app.curator = SimpleNamespace(curate=lambda rows: curated.extend(rows))
    app.tick(NOW)
    assert len(calls) == 1
    body = json.loads(calls[0].content)['content']
    assert 'new-model' in body and 'funding' not in body
    assert not curated and store.get_article(old)['state'] == 'skipped'
    assert store.get_article(low)['state'] == 'scored'
    assert store.get_article(good)['state'] == 'sent'


@pytest.mark.parametrize('kind', ['breaking', 'digest'])
def test_uncertain_delivery_blocks_second_post_even_after_restart(tmp_path, kind):
    path = tmp_path / 'news.sqlite3'
    store = Store(path)
    article(store, 'alpha', score=95 if kind == 'breaking' else 80, breaking=kind == 'breaking')
    calls = []
    def timeout(req):
        calls.append(req)
        raise httpx.ReadTimeout('lost acknowledgement')
    app = runtime(store, tmp_path, timeout)
    now = NOW - timedelta(hours=1) if kind == 'breaking' else NOW
    app.tick(now)
    store.close()
    store = Store(path)
    article(store, 'omega', score=96 if kind == 'breaking' else 85, breaking=kind == 'breaking')
    app = runtime(store, tmp_path, timeout)
    app.tick(now + timedelta(minutes=30))
    assert len(calls) == 1
    assert store.conn.execute('SELECT status FROM delivery_slots WHERE kind=?', (kind,)).fetchone()[0] == 'uncertain'
    store.close()


def test_known_connection_failure_releases_slot_for_retry(tmp_path):
    store = Store()
    article(store, 'recoverable')
    calls = []
    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            raise httpx.ConnectError('not connected')
        return httpx.Response(200, json={'id':'ok'})
    app = runtime(store, tmp_path, handler)
    app.tick(NOW)
    app.tick(NOW + timedelta(minutes=30))
    assert len(calls) == 2 and store.digest_sent('2026-09-08')


def test_crash_reservation_survives_restart(tmp_path):
    path = tmp_path / 'news.sqlite3'
    store = Store(path)
    article(store, 'crash-candidate')
    app = runtime(store, tmp_path, lambda req: (_ for _ in ()).throw(RuntimeError('simulated crash')))
    with pytest.raises(RuntimeError):
        app.tick(NOW)
    store.close()
    store = Store(path)
    calls = []
    article(store, 'after-crash')
    app = runtime(store, tmp_path, lambda req: calls.append(req) or httpx.Response(200, json={'id':'m'}))
    app.tick(NOW + timedelta(minutes=30))
    assert calls == []
    store.close()


def test_length_omitted_digest_items_remain_unsent(tmp_path):
    store = Store()
    ids = [article(store, title) for title in ['alpha', 'beta', 'gamma', 'delta', 'epsilon']]
    for key in ids:
        store.update_article(key, headline_ja='長' * 500, summary_ja='要' * 500)
    calls = []
    poster = runtime(store, tmp_path, lambda req: calls.append(req) or httpx.Response(200, json={'id':'m'})).poster
    assert poster.send_digest([store.get_article(key) for key in ids], NOW.date())
    content = json.loads(calls[0].content)['content']
    assert len(content) <= 2000
    for key in ids:
        row = store.get_article(key)
        assert (row['state'] == 'sent') == (row['url'] in content)
    assert len(store.get_articles('scored')) > 0


def test_curation_retry_survives_restart_and_is_bounded(tmp_path, monkeypatch):
    path = tmp_path / 'news.sqlite3'
    for attempt in range(3):
        store = Store(path)
        if attempt == 0:
            key = article(store, 'invalid-output', state='new')
        curator = Curator(store, Settings('x','stub','stub','stub'))
        monkeypatch.setattr(curator, '_request', lambda batch: (_ for _ in ()).throw(ValueError('invalid JSON')))
        curator.curate()
        row = store.get_article(key)
        assert row['curation_attempts'] == attempt + 1
        assert row['state'] == ('skipped' if attempt == 2 else 'new')
        store.close()


def test_valid_retry_keeps_candidate(tmp_path, monkeypatch):
    store = Store()
    key = article(store, 'recovered', state='new')
    curator = Curator(store, Settings('x','stub','stub','stub'))
    monkeypatch.setattr(curator, '_request', lambda batch: (_ for _ in ()).throw(ValueError('empty response')))
    curator.curate()
    monkeypatch.undo()
    curator.curate()
    assert store.get_article(key)['state'] == 'scored'


@pytest.mark.parametrize('base,expected', [('https://api.deepseek.com', True), ('https://api.openai.com/v1', False)])
def test_provider_json_options_do_not_leak_to_other_providers(base, expected):
    store = Store()
    key = article(store, 'structured', state='new')
    captured = []
    output = {'articles':[{'score':75,'breaking':False,'headline_ja':'新機能','summary_ja':'試せます','reason':'新規公開'}]}
    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(output)))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    Curator(store, Settings('x',base,'key','model'), client=client).curate()
    assert store.get_article(key)['state'] == 'scored'
    assert ('extra_body' in captured[0]) == expected
    if expected:
        assert captured[0]['extra_body'] == {'thinking':{'type':'disabled'}}


def test_existing_database_migrates_without_changing_articles(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    store = Store(path)
    key = article(store, 'preserve-history')
    store.mark_digest_sent('2026-09-07')
    store.conn.execute('ALTER TABLE articles DROP COLUMN curation_attempts')
    store.conn.commit()
    store.close()
    store = Store(path)
    assert store.get_article(key)['title'] == 'preserve-history'
    assert store.get_article(key)['curation_attempts'] == 0
    assert store.digest_sent('2026-09-07')
    store.close()
