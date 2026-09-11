import asyncio
import uuid

import pytest

from app import worker
from app.db import Store, utcnow_iso
from app.models import JobStatus
from app.worker import WorkerPool


def _new(**kw):
    base = dict(id=uuid.uuid4().hex, owner="local", prompt="p", alias="fast",
                tier="gpu", params={}, created_at=utcnow_iso())
    base.update(kw)
    return base


@pytest.fixture
async def store():
    s = Store(":memory:")
    await s.connect()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_process_one_completes(store):
    async def fake_run(alias, prompt, params, *, api_key=None, **kw):
        return f"ran {alias}:{prompt}"

    pool = WorkerPool(store, run_fn=fake_run)
    job = await store.add_job(**_new())
    ran = await pool.process_one("gpu")
    assert ran is True
    got = await store.get_job(job.id)
    assert got.status == JobStatus.DONE.value
    assert got.result == "ran fast:p"


@pytest.mark.asyncio
async def test_process_one_records_failure(store):
    async def boom(alias, prompt, params, *, api_key=None, **kw):
        raise ValueError("backend down")

    pool = WorkerPool(store, run_fn=boom)
    job = await store.add_job(**_new())
    await pool.process_one("gpu")
    got = await store.get_job(job.id)
    assert got.status == JobStatus.FAILED.value
    assert "backend down" in got.error


@pytest.mark.asyncio
async def test_empty_tier_returns_false(store):
    pool = WorkerPool(store, run_fn=None)
    assert await pool.process_one("gpu") is False


@pytest.mark.asyncio
async def test_slow_gpu_does_not_block_cpu(store):
    """A slow GPU job must not delay a CPU job (per-tier workers)."""
    gpu_started = asyncio.Event()
    release_gpu = asyncio.Event()
    order = []

    async def fake_run(alias, prompt, params, *, api_key=None, **kw):
        if alias == "fast":  # gpu tier
            gpu_started.set()
            await release_gpu.wait()  # hold the gpu worker
            order.append("gpu")
            return "gpu-done"
        else:  # cpu tier (background)
            order.append("cpu")
            return "cpu-done"

    pool = WorkerPool(store, run_fn=fake_run)
    gpu_job = await store.add_job(**_new(alias="fast", tier="gpu"))
    cpu_job = await store.add_job(**_new(alias="background", tier="cpu"))

    pool.start()
    try:
        # Wait until the gpu worker is blocked, then the cpu job should finish.
        await asyncio.wait_for(gpu_started.wait(), timeout=5)
        # cpu job completes while gpu is still held
        async def cpu_done():
            while True:
                j = await store.get_job(cpu_job.id)
                if j.status == JobStatus.DONE.value:
                    return
                await asyncio.sleep(0.05)
        await asyncio.wait_for(cpu_done(), timeout=5)
        assert order[0] == "cpu"  # cpu finished before gpu was released
        # now release gpu
        release_gpu.set()
        async def gpu_done():
            while True:
                j = await store.get_job(gpu_job.id)
                if j.status == JobStatus.DONE.value:
                    return
                await asyncio.sleep(0.05)
        await asyncio.wait_for(gpu_done(), timeout=5)
    finally:
        await pool.stop()


@pytest.mark.asyncio
async def test_worker_decrypts_key_and_scrubs(store):
    from app import crypto
    captured = {}

    async def fake_run(alias, prompt, params=None, *, api_key=None, **kw):
        captured["api_key"] = api_key
        return f"ran {alias}"

    await store.add_job(
        id="w1", owner="o", prompt="p", alias="fast", tier="gpu", params={},
        created_at="2026-01-01T00:00:00+00:00", enc_key=crypto.encrypt("sk-good-9"),
    )
    pool = worker.WorkerPool(store, run_fn=fake_run)
    ran = await pool.process_one("gpu")
    assert ran is True
    assert captured["api_key"] == "sk-good-9"          # decrypted before the call
    job = await store.get_job("w1")
    assert job.status == "done"
    assert job.enc_key is None                          # scrubbed after completion


@pytest.mark.asyncio
async def test_worker_scrubs_key_on_failure(store):
    from app import crypto

    async def boom(alias, prompt, params=None, *, api_key=None, **kw):
        raise RuntimeError("backend exploded")

    await store.add_job(
        id="w2", owner="o", prompt="p", alias="fast", tier="gpu", params={},
        created_at="2026-01-01T00:00:00+00:00", enc_key=crypto.encrypt("sk-good-9"),
    )
    pool = worker.WorkerPool(store, run_fn=boom)
    await pool.process_one("gpu")
    job = await store.get_job("w2")
    assert job.status == "failed"
    assert job.enc_key is None                          # scrubbed even on failure
