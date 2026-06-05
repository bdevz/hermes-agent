"""
Pluggable key/value + append-log storage backends.

Two backends with identical interfaces so the rest of the package never cares
where data lives:

- ``FileBackend``     JSON + JSONL under HERMES_HOME. Default; zero deps; used
                      in tests and single-box deployments without Postgres.
- ``PostgresBackend`` pgvector Postgres (Railway). Used when DATABASE_URL is set
                      so credentials/usage live in the shared system of record.

``get_backend()`` picks Postgres when DATABASE_URL is present, else File.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class StorageBackend:
    """Interface: a small KV table + an append-only event log."""

    # --- key/value (used by the credential store) ---
    def kv_get(self, namespace: str, key: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def kv_set(self, namespace: str, key: str, value: Dict[str, Any]) -> None:
        raise NotImplementedError

    def kv_delete(self, namespace: str, key: str) -> bool:
        raise NotImplementedError

    def kv_keys(self, namespace: str) -> List[str]:
        raise NotImplementedError

    # --- append-only log (used by usage tracking) ---
    def log_append(self, stream: str, record: Dict[str, Any]) -> None:
        raise NotImplementedError

    def log_read(self, stream: str, limit: int = 100) -> List[Dict[str, Any]]:
        raise NotImplementedError


class FileBackend(StorageBackend):
    """JSON/JSONL storage under a base directory (default: ``$HERMES_HOME``)."""

    def __init__(self, base_dir: Optional[str] = None):
        base = base_dir or os.getenv("HERMES_HOME") or os.path.expanduser("~/.hermes")
        self._root = Path(base) / "agentbox"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _kv_path(self, namespace: str) -> Path:
        return self._root / f"{namespace}.json"

    def _load_kv(self, namespace: str) -> Dict[str, Any]:
        path = self._kv_path(namespace)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _store_kv(self, namespace: str, data: Dict[str, Any]) -> None:
        path = self._kv_path(namespace)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)  # atomic
        try:
            os.chmod(path, 0o600)  # credentials live here — keep them private
        except OSError:
            pass

    def kv_get(self, namespace: str, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._load_kv(namespace).get(key)

    def kv_set(self, namespace: str, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            data = self._load_kv(namespace)
            data[key] = value
            self._store_kv(namespace, data)

    def kv_delete(self, namespace: str, key: str) -> bool:
        with self._lock:
            data = self._load_kv(namespace)
            existed = key in data
            if existed:
                del data[key]
                self._store_kv(namespace, data)
            return existed

    def kv_keys(self, namespace: str) -> List[str]:
        with self._lock:
            return sorted(self._load_kv(namespace).keys())

    def log_append(self, stream: str, record: Dict[str, Any]) -> None:
        path = self._root / f"{stream}.jsonl"
        with self._lock:
            with path.open("a") as fh:
                fh.write(json.dumps(record) + "\n")

    def log_read(self, stream: str, limit: int = 100) -> List[Dict[str, Any]]:
        path = self._root / f"{stream}.jsonl"
        if not path.exists():
            return []
        with self._lock:
            lines = path.read_text().splitlines()
        out: List[Dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


class PostgresBackend(StorageBackend):
    """
    Postgres-backed storage (Railway pgvector service).

    Lazily imports ``psycopg`` so the package is importable (and testable)
    without it. Tables are created on first use.
    """

    _KV_DDL = """
        CREATE TABLE IF NOT EXISTS agentbox_kv (
            namespace TEXT NOT NULL,
            key       TEXT NOT NULL,
            value     JSONB NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (namespace, key)
        );
    """
    _LOG_DDL = """
        CREATE TABLE IF NOT EXISTS agentbox_log (
            id     BIGSERIAL PRIMARY KEY,
            stream TEXT NOT NULL,
            record JSONB NOT NULL,
            ts     DOUBLE PRECISION NOT NULL
        );
        CREATE INDEX IF NOT EXISTS agentbox_log_stream_idx ON agentbox_log (stream, id DESC);
    """

    def __init__(self, dsn: Optional[str] = None):
        self._dsn = dsn or os.getenv("DATABASE_URL")
        if not self._dsn:
            raise ValueError("PostgresBackend requires a DSN or DATABASE_URL")
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ImportError(
                "PostgresBackend needs psycopg: pip install 'psycopg[binary]'"
            ) from exc
        self._psycopg = __import__("psycopg")
        self._init_schema()

    def _connect(self):
        return self._psycopg.connect(self._dsn)

    def _init_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._KV_DDL)
            cur.execute(self._LOG_DDL)
            conn.commit()

    def kv_get(self, namespace: str, key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM agentbox_kv WHERE namespace=%s AND key=%s",
                (namespace, key),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def kv_set(self, namespace: str, key: str, value: Dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agentbox_kv (namespace, key, value, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (namespace, key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                (namespace, key, Jsonb(value), time.time()),
            )
            conn.commit()

    def kv_delete(self, namespace: str, key: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM agentbox_kv WHERE namespace=%s AND key=%s",
                (namespace, key),
            )
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted

    def kv_keys(self, namespace: str) -> List[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT key FROM agentbox_kv WHERE namespace=%s ORDER BY key",
                (namespace,),
            )
            return [r[0] for r in cur.fetchall()]

    def log_append(self, stream: str, record: Dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agentbox_log (stream, record, ts) VALUES (%s, %s, %s)",
                (stream, Jsonb(record), time.time()),
            )
            conn.commit()

    def log_read(self, stream: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT record FROM agentbox_log WHERE stream=%s ORDER BY id DESC LIMIT %s",
                (stream, limit),
            )
            rows = [r[0] for r in cur.fetchall()]
        rows.reverse()  # chronological, matching FileBackend
        return rows


def get_backend() -> StorageBackend:
    """Return Postgres when DATABASE_URL is set, else the file backend."""
    if os.getenv("DATABASE_URL"):
        return PostgresBackend()
    return FileBackend()
