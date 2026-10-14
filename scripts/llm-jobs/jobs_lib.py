"""llm-jobs: a small job service whose workers are NanoClaw agent groups.

Python 3 stdlib only. Owns API keys, the job table and the dispatcher; the
running is done by NanoClaw: a job becomes a one-shot `ncl tasks create` on
the group for its tier, the agent wakes, does the job and calls the
service's MCP tool `deliver_result`. One job per group runs at a time.

Config comes from the environment (the systemd unit loads
~/.config/llm-jobs/jobs.env):

  LLMJOBS_DB          sqlite path (default ~/.local/share/llm-jobs/jobs.db)
  LLMJOBS_BIND        listen address (default 0.0.0.0)
  LLMJOBS_PORT        listen port (default 8378)
  LLMJOBS_NCL         path to the ncl binary (default /docker/nanoclaw/bin/ncl)
  LLMJOBS_TIERS       JSON: {"local": {"group": "jobs-local", "timeout_s": 1200, ...}, ...}
  LLMJOBS_PUBLIC_URL  what callers see (default https://jobs.rt-541.io)
  LLMJOBS_RETENTION_DAYS  default 30
  LLMJOBS_ARTIFACTS   directory of per-job output files, <dir>/<job_id>/<name> (default ~/.local/share/llm-jobs/artifacts)
"""

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

DEFAULT_TIERS = {
    "local": {"group": "jobs-local", "model": "qwen3-14b (vLLM on the B70 via the NanoClaw proxy)",
              "timeout_s": 1200, "speed": "fast", "cost": "free",
              "notes": "Default. Private, LAN-hosted, about 16k output tokens per job. Bulk and cheap work."},
    "claude": {"group": "jobs-claude", "model": "claude-sonnet-5 (Anthropic via the NanoClaw OneCLI vault)",
               "timeout_s": 1200, "speed": "fast", "cost": "metered",
               "daily_jobs": 200, "daily_tokens": 2000000,
               "notes": "Claude-quality output. Metered: per-key daily caps plus a tier-wide daily cap shared by all keys."},
}
# Optional per-tier keys `daily_jobs` / `daily_tokens` cap the whole tier for
# the UTC day, across every key; a key's own caps still apply underneath.

TERMINAL = ("done", "failed", "cancelled")

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
                 ".json": "application/json", ".txt": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8",
                 ".glb": "model/gltf-binary", ".pdf": "application/pdf"}


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class JobsError(Exception):
    def __init__(self, code, message, status=400, detail=None):
        super().__init__(message)
        self.code, self.message, self.status, self.detail = code, message, status, detail

    def envelope(self):
        e = {"error": self.code, "message": self.message}
        if self.detail is not None:
            e["detail"] = self.detail
        return e


class Config:
    def __init__(self, env=None):
        env = env if env is not None else os.environ
        home = os.path.expanduser("~")
        self.db_path = env.get("LLMJOBS_DB") or os.path.join(home, ".local", "share", "llm-jobs", "jobs.db")
        self.bind = env.get("LLMJOBS_BIND", "0.0.0.0")
        self.port = int(env.get("LLMJOBS_PORT", "8378"))
        self.ncl = env.get("LLMJOBS_NCL", "/docker/nanoclaw/bin/ncl")
        self.public_url = env.get("LLMJOBS_PUBLIC_URL", "https://jobs.rt-541.io")
        self.retention_days = int(env.get("LLMJOBS_RETENTION_DAYS", "30"))
        self.arbiter_url = env.get("LLMJOBS_ARBITER", "http://127.0.0.1:8390")
        self.artifacts_dir = env.get("LLMJOBS_ARTIFACTS") or os.path.join(home, ".local", "share", "llm-jobs", "artifacts")
        tiers = (env.get("LLMJOBS_TIERS") or "").strip()
        if tiers and tiers[0] in "'\"" and tiers[-1] == tiers[0]:
            tiers = tiers[1:-1]  # systemd EnvironmentFile keeps the quotes bash needs
        self.tiers = json.loads(tiers) if tiers else json.loads(json.dumps(DEFAULT_TIERS))
        self.poll_s = float(env.get("LLMJOBS_POLL_S", "3"))
        self.max_prompt_chars = int(env.get("LLMJOBS_MAX_PROMPT_CHARS", "200000"))
        self.max_result_chars = int(env.get("LLMJOBS_MAX_RESULT_CHARS", "400000"))


# ---------------------------------------------------------------------------
# storage

SCHEMA = """
create table if not exists keys (
  id text primary key,
  sha256 text not null unique,
  owner text not null,
  role text not null default 'user',          -- user | worker | admin
  tiers text not null default 'local',        -- comma list of allowed tiers
  daily_jobs integer not null default 50,
  daily_tokens integer not null default 200000,
  created_at text not null,
  revoked_at text,
  last_used_at text
);
create table if not exists jobs (
  id text primary key,
  key_id text not null,
  owner text not null,
  tier text not null,
  prompt text not null,
  params text not null default '{}',
  status text not null default 'queued',      -- queued | running | done | failed | cancelled
  created_at text not null,
  started_at text,
  finished_at text,
  task_id text,
  result text,
  error text,
  tokens_out integer not null default 0
);
create index if not exists jobs_status on jobs(status, tier, created_at);
create index if not exists jobs_owner on jobs(key_id, created_at);
"""


def hash_key(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path):
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("pragma journal_mode=wal")
            self.conn.executescript(SCHEMA)

    # -- keys ---------------------------------------------------------------
    def issue_key(self, owner, role="user", tiers=("local",), daily_jobs=50, daily_tokens=200000):
        key = "lj-" + secrets.token_urlsafe(32)
        kid = "k-" + uuid.uuid4().hex[:8]
        with self.lock:
            self.conn.execute(
                "insert into keys(id, sha256, owner, role, tiers, daily_jobs, daily_tokens, created_at) values(?,?,?,?,?,?,?,?)",
                (kid, hash_key(key), owner, role, ",".join(tiers), int(daily_jobs), int(daily_tokens), utcnow()))
            self.conn.commit()
        return kid, key

    def key_by_token(self, token):
        if not token:
            return None
        with self.lock:
            row = self.conn.execute("select * from keys where sha256=? and revoked_at is null", (hash_key(token),)).fetchone()
            if row:
                self.conn.execute("update keys set last_used_at=? where id=?", (utcnow(), row["id"]))
                self.conn.commit()
        return dict(row) if row else None

    def set_key_tiers(self, kid, tiers):
        with self.lock:
            n = self.conn.execute("update keys set tiers=? where id=? and revoked_at is null", (",".join(tiers), kid)).rowcount
            self.conn.commit()
        return n == 1

    def list_keys(self):
        with self.lock:
            return [dict(r) for r in self.conn.execute("select id, owner, role, tiers, daily_jobs, daily_tokens, created_at, revoked_at, last_used_at from keys order by created_at")]

    def revoke_key(self, kid):
        with self.lock:
            n = self.conn.execute("update keys set revoked_at=? where id=? and revoked_at is null", (utcnow(), kid)).rowcount
            self.conn.commit()
        return n == 1

    def usage_today(self, key_id=None, tier=None):
        """(jobs, output tokens) since UTC midnight, scoped to a key, a tier, or both."""
        where, args = ["created_at >= ?", "status != 'cancelled'"], [today() + "T00:00:00Z"]
        if key_id:
            where.append("key_id=?"); args.append(key_id)
        if tier:
            where.append("tier=?"); args.append(tier)
        with self.lock:
            row = self.conn.execute(
                "select count(*) as n, coalesce(sum(tokens_out),0) as t from jobs where " + " and ".join(where), args).fetchone()
        return int(row["n"]), int(row["t"])

    # -- jobs ---------------------------------------------------------------
    def create_job(self, key, tier, prompt, params):
        jid = "j-" + uuid.uuid4().hex[:12]
        with self.lock:
            self.conn.execute(
                "insert into jobs(id, key_id, owner, tier, prompt, params, status, created_at) values(?,?,?,?,?,?,?,?)",
                (jid, key["id"], key["owner"], tier, prompt, json.dumps(params or {}), "queued", utcnow()))
            self.conn.commit()
        return jid

    def get_job(self, jid):
        with self.lock:
            row = self.conn.execute("select * from jobs where id=?", (jid,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, key_id=None, limit=50):
        with self.lock:
            if key_id:
                rows = self.conn.execute("select * from jobs where key_id=? order by created_at desc limit ?", (key_id, limit))
            else:
                rows = self.conn.execute("select * from jobs order by created_at desc limit ?", (limit,))
            return [dict(r) for r in rows]

    def position(self, jid):
        job = self.get_job(jid)
        if not job or job["status"] != "queued":
            return None
        with self.lock:
            row = self.conn.execute("select count(*) as n from jobs where tier=? and status='queued' and created_at < ?",
                                    (job["tier"], job["created_at"])).fetchone()
        return int(row["n"]) + 1

    def next_queued(self, tier):
        with self.lock:
            row = self.conn.execute("select * from jobs where tier=? and status='queued' order by created_at limit 1", (tier,)).fetchone()
        return dict(row) if row else None

    def running(self, tier):
        with self.lock:
            row = self.conn.execute("select * from jobs where tier=? and status='running' order by started_at limit 1", (tier,)).fetchone()
        return dict(row) if row else None

    def mark_running(self, jid, task_id):
        with self.lock:
            self.conn.execute("update jobs set status='running', started_at=?, task_id=? where id=? and status='queued'", (utcnow(), task_id, jid))
            self.conn.commit()

    def finish(self, jid, result=None, error=None, status=None):
        st = status or ("done" if error is None else "failed")
        tokens = max(1, len(result) // 4) if result else 0
        with self.lock:
            n = self.conn.execute(
                "update jobs set status=?, finished_at=?, result=?, error=?, tokens_out=? where id=? and status in ('queued','running')",
                (st, utcnow(), result, error, tokens, jid)).rowcount
            self.conn.commit()
        return n == 1

    def sweep(self, retention_days):
        cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
        iso = datetime.fromtimestamp(cutoff, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.lock:
            n = self.conn.execute("delete from jobs where created_at < ?", (iso,)).rowcount
            self.conn.commit()
        return n


# ---------------------------------------------------------------------------
# NanoClaw bridge

WORKER_CONTRACT = """You are a headless job worker. Complete the job below and deliver the answer with the MCP tool `deliver_result` (server llm-jobs): job_id="{job_id}", result=<your complete answer as plain text or markdown>. Deliver exactly once, then stop. Do not post to any channel, do not ask questions, do not narrate. If the job cannot be completed, call deliver_result with job_id="{job_id}" and error=<one sentence why>. The result must be self-contained: the requester sees only what you deliver.{limits}

=== JOB {job_id} ===
{prompt}
=== END JOB ==="""


def worker_prompt(job, tier_cfg):
    params = {}
    try:
        params = json.loads(job.get("params") or "{}")
    except ValueError:
        pass
    limits = []
    if params.get("max_words"):
        limits.append("Keep the answer under %d words." % int(params["max_words"]))
    if params.get("format"):
        limits.append("Answer format: %s." % str(params["format"])[:200])
    if tier_cfg.get("contract_note"):
        limits.append(str(tier_cfg["contract_note"]).replace("{job_id}", job["id"]))
    return WORKER_CONTRACT.format(job_id=job["id"], prompt=job["prompt"], limits=(" " + " ".join(limits)) if limits else "")


class Ncl:
    """Thin wrapper around the ncl CLI. Replace in tests."""

    def __init__(self, path):
        self.path = path

    def _run(self, args, timeout=60):
        p = subprocess.run([self.path] + args, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise JobsError("ncl-error", "ncl %s failed: %s" % (" ".join(args[:2]), (p.stderr or p.stdout).strip()[:500]), 502)
        return p.stdout

    def group_id(self, folder):
        out = self._run(["groups", "list", "--json"])
        data = json.loads(out).get("data", [])
        for g in data:
            if g.get("folder") == folder:
                return g["id"]
        raise JobsError("no-group", "NanoClaw group with folder %r not found" % folder, 503)

    def create_task(self, group_id, name, prompt):
        payload = json.dumps({"group": group_id, "name": name, "prompt": prompt, "process-after": utcnow()})
        p = subprocess.run([self.path, "tasks", "create", "--stdin-json", "--json"], input=payload,
                           capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            raise JobsError("ncl-error", "ncl tasks create failed: %s" % (p.stderr or p.stdout).strip()[:500], 502)
        try:
            data = json.loads(p.stdout)
        except ValueError:
            raise JobsError("ncl-error", "ncl tasks create returned non-JSON", 502)
        d = data.get("data") if isinstance(data, dict) else None
        tid = (d or {}).get("id") if isinstance(d, dict) else None
        if not tid and isinstance(data, dict):
            tid = data.get("id")
        if not tid:
            raise JobsError("ncl-error", "ncl tasks create returned no id: %s" % p.stdout[:300], 502)
        return tid

    def cancel_task(self, group_id, task_id):
        try:
            self._run(["tasks", "cancel", "--id", task_id, "--group", group_id])
            return True
        except JobsError:
            return False


class Dispatcher(threading.Thread):
    """One job per tier at a time: pick the oldest queued job, create the
    NanoClaw task, wait for deliver_result (the HTTP side calls
    store.finish), time out and cancel if the agent never delivers."""

    def __init__(self, cfg, store, ncl, log=print):
        super().__init__(daemon=True, name="llm-jobs-dispatcher")
        self.cfg, self.store, self.ncl, self.log = cfg, store, ncl, log
        self.stop_event = threading.Event()
        self._gids = {}
        self._last_sweep = 0

    def group_for(self, tier):
        folder = self.cfg.tiers[tier]["group"]
        if folder not in self._gids:
            self._gids[folder] = self.ncl.group_id(folder)
        return self._gids[folder]

    def tick(self):
        now = time.time()
        for tier, tcfg in self.cfg.tiers.items():
            running = self.store.running(tier)
            if running:
                started = datetime.strptime(running["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
                if now - started > tcfg.get("timeout_s", 1200):
                    self.log("job %s timed out on %s; cancelling task %s" % (running["id"], tier, running["task_id"]))
                    try:
                        self.ncl.cancel_task(self.group_for(tier), running["task_id"])
                    except JobsError as e:
                        self.log("cancel failed: %s" % e.message)
                    self.store.finish(running["id"], error="timed out after %ds without a delivery" % tcfg.get("timeout_s", 1200))
                continue
            job = self.store.next_queued(tier)
            if not job:
                continue
            try:
                gid = self.group_for(tier)
                tid = self.ncl.create_task(gid, "job-" + job["id"], worker_prompt(job, tcfg))
            except JobsError as e:
                self.log("dispatch of %s failed: %s" % (job["id"], e.message))
                self.store.finish(job["id"], error="dispatch failed: %s" % e.message)
                continue
            self.store.mark_running(job["id"], tid)
            self.log("job %s -> task %s on %s" % (job["id"], tid, tier))
        if now - self._last_sweep > 3600:
            self.sweep_now()
            self._last_sweep = now

    def sweep_now(self):
        n = self.store.sweep(self.cfg.retention_days)
        if n:
            self.log("swept %d jobs older than %d days" % (n, self.cfg.retention_days))
        # artifact folders whose job is gone (swept or never stored) go too
        root = self.cfg.artifacts_dir
        if os.path.isdir(root):
            for name in os.listdir(root):
                path = os.path.join(root, name)
                if os.path.isdir(path) and not self.store.get_job(name):
                    shutil.rmtree(path, ignore_errors=True)
                    self.log("removed artifacts of %s" % name)

    def cancel(self, job):
        if job["status"] == "running" and job.get("task_id"):
            try:
                self.ncl.cancel_task(self.group_for(job["tier"]), job["task_id"])
            except JobsError:
                pass
        return self.store.finish(job["id"], status="cancelled")

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - the loop must survive
                self.log("dispatcher error: %s" % e)
            self.stop_event.wait(self.cfg.poll_s)


# ---------------------------------------------------------------------------
# the operations both REST and MCP expose

class Arbiter:
    """Client for the host gpu-arbiter (scripts/gpu-arbiter), which owns the GPU swaps."""

    def __init__(self, url):
        self.url = url.rstrip("/")

    def _req(self, method, path, body=None):
        import urllib.error
        import urllib.request
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise JobsError("arbiter-error", e.read().decode()[:300], 502)
        except OSError as e:
            raise JobsError("arbiter-down", "gpu-arbiter unreachable: %s" % e, 503)

    def post(self, body):
        return self._req("POST", "/photos", body)

    def get(self, pid):
        return self._req("GET", "/photos/" + pid)


class Service:
    def __init__(self, cfg, store, dispatcher):
        self.cfg, self.store, self.dispatcher = cfg, store, dispatcher
        self.arbiter = Arbiter(cfg.arbiter_url)

    def tiers(self):
        return [{"tier": t, **{k: v for k, v in c.items() if k != "group"}} for t, c in self.cfg.tiers.items()]

    def submit(self, key, prompt, tier="local", params=None):
        if key["role"] not in ("user", "admin"):
            raise JobsError("forbidden", "this key cannot submit jobs", 403)
        if not isinstance(prompt, str) or not prompt.strip():
            raise JobsError("bad-request", "prompt must be a non-empty string", 400)
        if len(prompt) > self.cfg.max_prompt_chars:
            raise JobsError("bad-request", "prompt exceeds %d characters" % self.cfg.max_prompt_chars, 400)
        tier = tier or "local"
        if tier not in self.cfg.tiers:
            raise JobsError("bad-request", "unknown tier %r; tiers: %s" % (tier, ", ".join(self.cfg.tiers)), 400)
        allowed = [t.strip() for t in key["tiers"].split(",") if t.strip()]
        if tier not in allowed and key["role"] != "admin":
            raise JobsError("forbidden", "this key may not use tier %r (allowed: %s)" % (tier, ", ".join(allowed)), 403)
        n, toks = self.store.usage_today(key["id"])
        if n >= key["daily_jobs"]:
            raise JobsError("quota", "daily job cap reached (%d)" % key["daily_jobs"], 429)
        if toks >= key["daily_tokens"]:
            raise JobsError("quota", "daily output-token cap reached (%d)" % key["daily_tokens"], 429)
        # tier-wide ceiling shared by every key (NanoClaw has no per-group usage
        # cap, so this is the only thing bounding a metered tier's daily spend)
        tcfg = self.cfg.tiers[tier]
        if tcfg.get("daily_jobs") or tcfg.get("daily_tokens"):
            tn, ttoks = self.store.usage_today(tier=tier)
            if tcfg.get("daily_jobs") and tn >= int(tcfg["daily_jobs"]):
                raise JobsError("quota", "tier %r daily job cap reached (%d); try again after 00:00 UTC" % (tier, int(tcfg["daily_jobs"])), 429)
            if tcfg.get("daily_tokens") and ttoks >= int(tcfg["daily_tokens"]):
                raise JobsError("quota", "tier %r daily output-token cap reached (%d); try again after 00:00 UTC" % (tier, int(tcfg["daily_tokens"])), 429)
        if params is not None and not isinstance(params, dict):
            raise JobsError("bad-request", "params must be an object", 400)
        jid = self.store.create_job(key, tier, prompt, params or {})
        return self.status(key, jid)

    def _own(self, key, jid):
        job = self.store.get_job(jid)
        if not job or (key["role"] != "admin" and job["key_id"] != key["id"]):
            raise JobsError("not-found", "no such job %s" % jid, 404)
        return job

    def status(self, key, jid):
        job = self._own(key, jid)
        return {"job_id": job["id"], "status": job["status"], "tier": job["tier"],
                "position": self.store.position(job["id"]), "created_at": job["created_at"],
                "started_at": job["started_at"], "finished_at": job["finished_at"],
                "error": job["error"] if job["status"] == "failed" else None}

    def result(self, key, jid):
        job = self._own(key, jid)
        out = {"job_id": job["id"], "status": job["status"], "result": job["result"] if job["status"] == "done" else None,
               "error": job["error"], "finished_at": job["finished_at"], "tokens_out": job["tokens_out"]}
        arts = self.artifacts(job)
        if arts is not None:
            out["artifacts"] = arts
        return out

    def artifacts(self, job):
        """Files the worker left under <artifacts>/<job_id>/, or None when the job has no folder and its tier makes none."""
        d = os.path.join(self.cfg.artifacts_dir, job["id"])
        tcfg = self.cfg.tiers.get(job["tier"]) or {}
        if not os.path.isdir(d):
            return [] if tcfg.get("artifacts") else None
        base = self.cfg.public_url.rstrip("/")
        return [{"name": n, "bytes": os.path.getsize(os.path.join(d, n)),
                 "url": "%s/api/jobs/%s/artifacts/%s" % (base, job["id"], n)}
                for n in sorted(os.listdir(d)) if SAFE_NAME.match(n) and os.path.isfile(os.path.join(d, n))]

    def request_photo(self, key, jid, name, prompt=None):
        """Worker: queue a photo pass of one of a running job's artifact images with the gpu-arbiter."""
        if key["role"] not in ("worker", "admin"):
            raise JobsError("forbidden", "only worker keys request photos", 403)
        job = self.store.get_job(jid)
        if not job or job["status"] != "running":
            raise JobsError("bad-request", "job %s is not running" % jid, 400)
        if not SAFE_NAME.match(name or "") or ".." in name or not name.lower().endswith(".png"):
            raise JobsError("bad-request", "image must be a .png name in the job's artifact folder", 400)
        d = os.path.join(self.cfg.artifacts_dir, jid)
        src = os.path.join(d, name)
        if not os.path.isfile(src):
            raise JobsError("not-found", "no such artifact %s" % name, 404)
        body = {"src": src, "dst": os.path.join(d, "photo-" + name)}
        if prompt:
            body["prompt"] = str(prompt)[:2000]
        r = self.arbiter.post(body)
        return {"photo_id": r["id"], "position": r.get("position"), "output": "photo-" + name}

    def photo_status(self, key, pid):
        if key["role"] not in ("worker", "admin"):
            raise JobsError("forbidden", "only worker keys check photos", 403)
        r = self.arbiter.get(pid)
        if r is None:
            raise JobsError("not-found", "no such photo %s" % pid, 404)
        return r

    def artifact(self, key, jid, name):
        job = self._own(key, jid)
        if not SAFE_NAME.match(name or "") or ".." in name:
            raise JobsError("not-found", "no such artifact", 404)
        path = os.path.join(self.cfg.artifacts_dir, job["id"], name)
        if not os.path.isfile(path):
            raise JobsError("not-found", "no such artifact %s" % name, 404)
        return path, CONTENT_TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream")

    def cancel(self, key, jid):
        job = self._own(key, jid)
        if job["status"] in TERMINAL:
            return {"job_id": jid, "cancelled": False, "message": "job already %s" % job["status"]}
        ok = self.dispatcher.cancel(job)
        return {"job_id": jid, "cancelled": ok, "message": "cancelled" if ok else "could not cancel"}

    def list(self, key, limit=50):
        rows = self.store.list_jobs(None if key["role"] == "admin" else key["id"], min(int(limit or 50), 200))
        return [{"job_id": r["id"], "status": r["status"], "tier": r["tier"], "created_at": r["created_at"],
                 "finished_at": r["finished_at"], "owner": r["owner"]} for r in rows]

    def deliver(self, key, jid, result=None, error=None):
        if key["role"] not in ("worker", "admin"):
            raise JobsError("forbidden", "only worker keys deliver results", 403)
        job = self.store.get_job(jid)
        if not job:
            raise JobsError("not-found", "no such job %s" % jid, 404)
        if job["status"] in TERMINAL:
            return {"job_id": jid, "accepted": False, "message": "job already %s" % job["status"]}
        if result is not None and not isinstance(result, str):
            result = json.dumps(result)
        if result is not None and len(result) > self.cfg.max_result_chars:
            result = result[: self.cfg.max_result_chars] + "\n\n[truncated by llm-jobs at %d characters]" % self.cfg.max_result_chars
        if not result and not error:
            raise JobsError("bad-request", "deliver_result needs result or error", 400)
        ok = self.store.finish(jid, result=result if result else None, error=error if not result else None)
        return {"job_id": jid, "accepted": ok}
