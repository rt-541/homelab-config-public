import uuid

import pytest

from app.db import Store, utcnow_iso
from app.models import JobStatus


@pytest.fixture
async def store():
    s = Store(":memory:")
    await s.connect()
    yield s
    await s.close()


def _new(**kw):
    base = dict(
        id=uuid.uuid4().hex, owner="local", prompt="hi", alias="fast",
        tier="gpu", params={}, created_at=utcnow_iso(),
    )
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_add_job_is_queued(store):
    job = await store.add_job(**_new())
    assert job.status == JobStatus.QUEUED.value
    fetched = await store.get_job(job.id)
    assert fetched.id == job.id
    assert fetched.position == 1


@pytest.mark.asyncio
async def test_queue_position_counts_earlier(store):
    import asyncio
    a = await store.add_job(**_new(tier="gpu", created_at="2020-01-01T00:00:00+00:00"))
    b = await store.add_job(**_new(tier="gpu", created_at="2020-01-01T00:00:01+00:00"))
    c = await store.add_job(**_new(tier="gpu", created_at="2020-01-01T00:00:02+00:00"))
    assert (await store.queue_position(a.id)) == 1
    assert (await store.queue_position(b.id)) == 2
    assert (await store.queue_position(c.id)) == 3
    # different tier is independent
    d = await store.add_job(**_new(tier="cpu", created_at="2020-01-01T00:00:03+00:00"))
    assert (await store.queue_position(d.id)) == 1


@pytest.mark.asyncio
async def test_claim_moves_to_running_fifo(store):
    a = await store.add_job(**_new(tier="gpu", created_at="2020-01-01T00:00:00+00:00"))
    b = await store.add_job(**_new(tier="gpu", created_at="2020-01-01T00:00:01+00:00"))
    claimed = await store.claim_next("gpu", utcnow_iso())
    assert claimed.id == a.id
    assert claimed.status == JobStatus.RUNNING.value
    # b is now position 1
    assert (await store.queue_position(b.id)) == 1
    # claiming a tier with nothing queued returns None
    assert (await store.claim_next("cpu", utcnow_iso())) is None


@pytest.mark.asyncio
async def test_complete_writes_result(store):
    job = await store.add_job(**_new())
    await store.claim_next("gpu", utcnow_iso())
    await store.complete_job(job.id, "the answer", utcnow_iso())
    got = await store.get_job(job.id)
    assert got.status == JobStatus.DONE.value
    assert got.result == "the answer"
    assert got.finished_at


@pytest.mark.asyncio
async def test_fail_writes_error(store):
    job = await store.add_job(**_new())
    await store.claim_next("gpu", utcnow_iso())
    await store.fail_job(job.id, "boom", utcnow_iso())
    got = await store.get_job(job.id)
    assert got.status == JobStatus.FAILED.value
    assert got.error == "boom"


@pytest.mark.asyncio
async def test_cancel_only_queued(store):
    job = await store.add_job(**_new())
    assert await store.cancel_job(job.id, "local", utcnow_iso()) is True
    # cannot cancel again
    assert await store.cancel_job(job.id, "local", utcnow_iso()) is False


@pytest.mark.asyncio
async def test_cancel_wrong_owner(store):
    job = await store.add_job(**_new(owner="alice"))
    assert await store.cancel_job(job.id, "bob", utcnow_iso()) is False


@pytest.mark.asyncio
async def test_prune_terminal_only(store):
    old = await store.add_job(**_new())
    await store.claim_next("gpu", utcnow_iso())
    await store.complete_job(old.id, "x", "2000-01-01T00:00:00+00:00")
    live = await store.add_job(**_new())  # still queued
    removed = await store.prune("2010-01-01T00:00:00+00:00")
    assert removed == 1
    assert await store.get_job(old.id) is None
    assert await store.get_job(live.id) is not None


@pytest.mark.asyncio
async def test_list_jobs_by_owner(store):
    await store.add_job(**_new(owner="alice"))
    await store.add_job(**_new(owner="bob"))
    assert len(await store.list_jobs("alice")) == 1
    assert len(await store.list_jobs("bob")) == 1


@pytest.mark.asyncio
async def test_add_job_stores_and_scrubs_enc_key(store):
    job = await store.add_job(
        id="k1", owner="ownerhash", prompt="p", alias="fast", tier="gpu",
        params={}, created_at="2026-01-01T00:00:00+00:00", enc_key="ENC",
    )
    assert job.enc_key == "ENC"
    again = await store.get_job("k1")
    assert again.enc_key == "ENC"
    await store.scrub_key("k1")
    assert (await store.get_job("k1")).enc_key is None


@pytest.mark.asyncio
async def test_cancel_job_scrubs_enc_key(store):
    await store.add_job(
        id="c1", owner="o", prompt="p", alias="fast", tier="gpu", params={},
        created_at="2026-01-01T00:00:00+00:00", enc_key="ENC",
    )
    ok = await store.cancel_job("c1", "o", "2026-01-01T00:01:00+00:00")
    assert ok is True
    job = await store.get_job("c1")
    assert job.status == "cancelled"
    assert job.enc_key is None  # key scrubbed on cancel (terminal)
