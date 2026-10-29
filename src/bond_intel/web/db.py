from __future__ import annotations
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import lru_cache
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from bond_intel.db.jsonb import dumps
TTL_SECONDS = 60.0
_cache: dict = {}
_lock = threading.Lock()
_generation = 0

@lru_cache
def engine() -> Engine:
    from bond_intel.web.auth import public_view
    connect_args = {'options': '-c timezone=Asia/Kolkata'}
    url = os.environ.get('BI_DASHBOARD_DB_URL')
    if not url:
        from bond_intel.db.engine import dashboard_url
        url = dashboard_url()
    elif 'sslmode=verify' in url and 'sslrootcert' not in url:
        import certifi
        connect_args['sslrootcert'] = certifi.where()
    if public_view():
        connect_args['options'] += ' -c default_transaction_read_only=on'
    return create_engine(url, pool_pre_ping=False, pool_size=5, max_overflow=5, pool_recycle=240, connect_args=connect_args)

def _key(kind: str, sql: str, params: dict):
    return (kind, sql, repr(sorted(params.items())))

def _read(kind: str, sql: str, params: dict, cache: bool):
    k = _key(kind, sql, params)
    now = time.monotonic()
    if cache:
        with _lock:
            hit = _cache.get(k)
            generation = _generation
        if hit and now - hit[0] < TTL_SECONDS:
            return _copy(hit[1])
    for attempt in (1, 2):
        try:
            with engine().connect() as c:
                res = c.execute(text(sql), params)
                value = [dict(r._mapping) for r in res] if kind == 'rows' else res.scalar()
            break
        except OperationalError:
            if attempt == 2:
                raise
            engine().dispose()
    if cache:
        with _lock:
            if generation == _generation:
                _keep(k, now, value)
    return _copy(value)

def _keep(k, now: float, value) -> None:
    from bond_intel.web.auth import public_view
    for old in [key for key, (at, _) in _cache.items() if now - at >= TTL_SECONDS]:
        del _cache[old]
    if len(_cache) >= (16 if public_view() else 500):
        _cache.clear()
    _cache[k] = (now, value)

def _copy(value):
    return [dict(r) for r in value] if isinstance(value, list) else value
_pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix='db-warm')

def warm(*queries: tuple) -> None:
    futures = [_pool.submit(_read, kind, sql, params, True) for kind, sql, params in queries]
    for f in futures:
        try:
            f.result()
        except Exception:
            pass

def forget() -> None:
    global _generation
    with _lock:
        _generation += 1
        _cache.clear()

def rows(sql: str, cache: bool=True, **params) -> list[dict]:
    return _read('rows', sql, params, cache)

def row(sql: str, cache: bool=True, **params) -> dict | None:
    out = rows(sql, cache, **params)
    return out[0] if out else None

def scalar(sql: str, cache: bool=True, **params):
    return _read('scalar', sql, params, cache)

def execute(sql: str, actor: str | None=None, **params) -> int:
    try:
        with engine().begin() as c:
            if actor:
                c.execute(text("SELECT set_config('bi.actor', :a, true)"), {'a': actor})
            return c.execute(text(sql), params).rowcount
    finally:
        forget()

def call(sql: str, actor: str | None=None, **params):
    try:
        with engine().begin() as c:
            if actor:
                c.execute(text("SELECT set_config('bi.actor', :a, true)"), {'a': actor})
            return c.execute(text(sql), params).scalar()
    finally:
        forget()

@contextmanager
def raw():
    with engine().connect() as c:
        conn = c.connection.driver_connection
        try:
            yield conn
        finally:
            conn.rollback()

def put_entry(key: str, entry_key: str, entry: dict, actor: str) -> None:
    execute('INSERT INTO cfg.setting (key, value, updated_by) VALUES (:k, jsonb_build_object(CAST(:e AS text), CAST(:v AS jsonb)), :a) ON CONFLICT (key) DO UPDATE SET value = cfg.setting.value || jsonb_build_object(CAST(:e AS text), CAST(:v AS jsonb)), updated_by = :a', actor=actor, k=key, e=entry_key, v=dumps(entry), a=actor)

def drop_entry(key: str, entry_key: str, actor: str) -> None:
    execute('UPDATE cfg.setting SET value = value - CAST(:e AS text), updated_by = :a WHERE key = :k', actor=actor, k=key, e=entry_key, a=actor)

def put(key: str, value, actor: str) -> None:
    execute('INSERT INTO cfg.setting (key, value, updated_by) VALUES (:k, CAST(:v AS jsonb), :a) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by', actor=actor, k=key, v=dumps(value), a=actor)
SETTINGS_SQL = 'SELECT key, value FROM cfg.setting'
SETTINGS_Q = ('rows', SETTINGS_SQL, {})
SETTING_SQL = 'SELECT value FROM cfg.setting WHERE key = :k'

def settings() -> dict:
    return {r['key']: r['value'] for r in rows(SETTINGS_SQL)}

def setting(key: str, default=None, cache: bool=True):
    v = settings().get(key) if cache else scalar(SETTING_SQL, cache=False, k=key)
    return default if v is None else v

def audit(actor: str, action: str, target: str | None=None, message: str | None=None, **details) -> None:
    execute("INSERT INTO ops.event (kind, actor, action, target, message, details) VALUES ('audit', :a, :ac, :t, :m, CAST(:d AS jsonb))", a=actor, ac=action, t=target, m=message, d=dumps(details))
MAX_ATTEMPTS = {'obpp.scrape': 1, 'ref.enrich': 1, 'report.send': 1, 'exchange.backfill': 2}

def enqueue(job_type: str, lane: str, actor: str, params: dict | None=None, *, task_key: str | None=None, dedupe: str | None=None) -> bool:
    n = execute("INSERT INTO ops.job (task_key, job_type, lane, params, trigger, requested_by, dedupe_key, max_attempts) VALUES (coalesce(:tk, (SELECT t.task_key FROM ops.task t WHERE t.task_key = :j)), :j, :l, CAST(:p AS jsonb), 'dashboard', :u, :d, :m) ON CONFLICT DO NOTHING", tk=task_key, j=job_type, l=lane, p=json.dumps(params or {}), u=actor, d=dedupe, m=MAX_ATTEMPTS.get(job_type, 3))
    audit(actor, 'job.enqueue', task_key or job_type, params=params or {}, queued=bool(n))
    if n:
        from bond_intel.worker.signals import request_wake
        request_wake()
    return bool(n)
