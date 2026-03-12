from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row


POSTGRES_DSN = os.getenv("GATEWAY_DATABASE_DSN", "postgresql://rag:rag@postgres:5432/gateway_app?sslmode=disable")
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"


class GatewayDatabase:
    def __init__(self, dsn: str, migrations_dir: Path):
        self._dsn = dsn
        self._migrations_dir = migrations_dir

    @property
    def dsn(self) -> str:
        return self._dsn

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            yield conn

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                for migration in sorted(self._migrations_dir.glob("*.sql")):
                    cur.execute(migration.read_text(encoding="utf-8"))
            conn.commit()


def to_json(data: dict[str, Any] | list[Any] | None) -> str:
    payload: dict[str, Any] | list[Any]
    if data is None:
        payload = {}
    else:
        payload = data
    return json.dumps(payload, ensure_ascii=False)
