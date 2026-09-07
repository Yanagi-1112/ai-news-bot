import httpx

from bot.collector import Collector
from bot.store import Store


def test_not_modified_response_reuses_cache_without_warning(caplog):
    store = Store()
    store.save_source_headers('rss', 'old-etag', None)
    source = {'id':'rss', 'url':'https://example.com/rss', 'type':'rss', 'category':'official'}
    def handler(request):
        assert request.headers['If-None-Match'] == 'old-etag'
        return httpx.Response(304)
    collector = Collector(store, httpx.Client(transport=httpx.MockTransport(handler)))
    assert collector.collect([source]) == []
    assert not caplog.records
    assert store.source_headers('rss') == ('old-etag', None)


def test_failed_fetch_does_not_replace_last_successful_cache_headers():
    store = Store()
    store.save_source_headers('rss', 'good-etag', None)
    source = {'id':'rss', 'url':'https://example.com/rss', 'type':'rss', 'category':'official'}
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, headers={'ETag':'error-etag'})))
    assert Collector(store, client).collect([source]) == []
    assert store.source_headers('rss') == ('good-etag', None)
