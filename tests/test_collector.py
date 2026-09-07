import httpx

from bot.collector import Collector
from bot.store import Store


def source(source_id, url):
    return {"id": source_id, "name": source_id, "type": "rss", "url": url, "category": "official", "terms_url": "https://example.com/terms", "checked_date": "2026-09-07"}


def test_broken_rss_does_not_stop_other_source():
    def handler(request):
        if "bad" in str(request.url):
            return httpx.Response(200, content=b"<rss><broken>")
        return httpx.Response(200, content=b"<?xml version='1.0'?><rss><channel><item><title>Good</title><link>https://example.com/good</link></item></channel></rss>")
    collector = Collector(Store(), httpx.Client(transport=httpx.MockTransport(handler)))
    result = collector.collect([source("bad", "https://source.test/bad"), source("good", "https://source.test/good")])
    assert [item["title"] for item in result] == ["Good"]
