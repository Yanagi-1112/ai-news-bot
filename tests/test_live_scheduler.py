"""Exercise the real scheduler executor, without network or Discord writes."""
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED
from apscheduler.schedulers.blocking import BlockingScheduler

from bot.config import Settings
from bot.scheduler import JST, NewsScheduler
from bot.store import Store


def test_serve_scheduled_tick_can_access_persistent_database(tmp_path, monkeypatch):
    events = []
    triggers = []
    engine = BlockingScheduler(timezone=JST)
    # A completed Future may run its callback synchronously in the scheduler's
    # submitting thread. Exercise that legal ordering with a real worker thread,
    # so the test cannot depend on a lucky race between submit() and add_done_callback().
    real_submit = ThreadPoolExecutor.submit

    def finish_before_callback(self, function, *args, **kwargs):
        future = real_submit(self, function, *args, **kwargs)
        future.result(timeout=5)
        return future

    monkeypatch.setattr(ThreadPoolExecutor, 'submit', finish_before_callback)

    def completed(event):
        events.append(event)

    def submitted(_event):
        # Submission is announced after the scheduler updates its job store.
        # Stopping from the completion callback can clear that store before its
        # update when a Future finishes before add_done_callback(). Wait for the
        # actual worker here so all completion assertions remain meaningful.
        engine.shutdown(wait=True)

    engine.add_listener(completed, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
    engine.add_listener(submitted, EVENT_JOB_SUBMITTED)
    real_add_job = engine.add_job

    def run_immediately(*args, **kwargs):
        kwargs['next_run_time'] = datetime.now(JST)
        job = real_add_job(*args, **kwargs)
        triggers.append(job.trigger)
        return job

    monkeypatch.setattr(engine, 'add_job', run_immediately)
    monkeypatch.setattr('bot.scheduler.BlockingScheduler', lambda **kwargs: engine)

    class Collector:
        def collect(self, sources):
            return []

    class Curator:
        def curate(self, articles):
            return None

    store = Store(tmp_path / 'articles.sqlite3')
    settings = Settings('unused', 'stub', 'stub', 'stub', data_dir=tmp_path)
    runtime = NewsScheduler(store, Collector(), Curator(), object(), settings, [])
    try:
        runtime.serve()
        assert len(events) == 1
        assert events[0].exception is None
        assert store.is_initialized()
        assert (tmp_path / 'heartbeat').exists()
        # 起動時刻から30分後ではなく、朝8時の巡回が予定される。
        assert triggers[0].get_next_fire_time(None, datetime(2026, 9, 8, 7, 47, tzinfo=JST)) == datetime(2026, 9, 8, 8, 0, tzinfo=JST)
    finally:
        store.close()
