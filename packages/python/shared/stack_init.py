from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .qdrant_store import ensure_qdrant_collection
from .storage import ObjectStorageClient


REPO_ROOT = Path(__file__).resolve().parents[3]
GATEWAY_MIGRATIONS_DIR = REPO_ROOT / "apps" / "services" / "api-gateway" / "database" / "migrations"
KB_MIGRATIONS_DIR = REPO_ROOT / "apps" / "services" / "knowledge-base" / "database" / "migrations"
GATEWAY_DATABASE_DSN = os.getenv("GATEWAY_DATABASE_DSN", "postgresql://rag:rag@postgres:5432/gateway_app?sslmode=disable")
KB_DATABASE_DSN = os.getenv("KB_DATABASE_DSN", "postgresql://rag:rag@postgres:5432/kb_app?sslmode=disable")
KB_BLOB_ROOT = Path(os.getenv("KB_BLOB_ROOT", "/data/kb")).resolve()
INIT_RETRY_SECONDS = max(float(os.getenv("STACK_INIT_RETRY_SECONDS", "2")), 0.5)
INIT_RETRY_COUNT = max(int(os.getenv("STACK_INIT_RETRY_COUNT", "30")), 1)


@dataclass(frozen=True)
class MigrationFile:
    version: str
    checksum: str
    sql: str


def _wait_for_database(name: str, dsn: str) -> None:
    last_error = ""
    for _ in range(INIT_RETRY_COUNT):
        try:
            with psycopg.connect(dsn, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                conn.commit()
            return
        except psycopg.Error as exc:
            last_error = str(exc)
            time.sleep(INIT_RETRY_SECONDS)
    raise RuntimeError(f"{name} database is unavailable: {last_error}")


def _wait_for_vector_store() -> dict[str, object]:
    last_error = ""
    for _ in range(INIT_RETRY_COUNT):
        try:
            return ensure_qdrant_collection()
        except Exception as exc:
            last_error = str(exc)
            time.sleep(INIT_RETRY_SECONDS)
    raise RuntimeError(f"qdrant vector store is unavailable: {last_error}")


def _migration_checksum(raw_sql: str) -> str:
    return hashlib.sha256(raw_sql.encode("utf-8")).hexdigest()


def _load_migration_files(migrations_dir: Path) -> list[MigrationFile]:
    files: list[MigrationFile] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        raw_sql = path.read_text(encoding="utf-8")
        files.append(
            MigrationFile(
                version=path.name,
                checksum=_migration_checksum(raw_sql),
                sql=raw_sql,
            )
        )
    return files


def _ensure_migration_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def _load_applied_migrations(cur) -> dict[str, str]:
    cur.execute(
        """
        SELECT version, checksum
        FROM schema_migrations
        ORDER BY version ASC
        """
    )
    return {str(row["version"]): str(row["checksum"]) for row in cur.fetchall()}


def _select_pending_migrations(files: list[MigrationFile], applied: dict[str, str]) -> list[MigrationFile]:
    pending: list[MigrationFile] = []
    for migration in files:
        applied_checksum = applied.get(migration.version)
        if applied_checksum is None:
            pending.append(migration)
            continue
        if applied_checksum != migration.checksum:
            raise RuntimeError(
                f"migration checksum mismatch for {migration.version}: expected {applied_checksum}, got {migration.checksum}"
            )
    return pending


def _apply_migrations(dsn: str, migrations_dir: Path) -> dict[str, int]:
    files = _load_migration_files(migrations_dir)
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            _ensure_migration_table(cur)
        conn.commit()

        with conn.cursor() as cur:
            applied = _load_applied_migrations(cur)
        pending = _select_pending_migrations(files, applied)

        for migration in pending:
            with conn.cursor() as cur:
                cur.execute(migration.sql)
                cur.execute(
                    """
                    INSERT INTO schema_migrations (version, checksum)
                    VALUES (%s, %s)
                    ON CONFLICT (version) DO NOTHING
                    """,
                    (migration.version, migration.checksum),
                )
            conn.commit()
    return {
        "available": len(files),
        "applied": len(pending),
        "already_applied": len(files) - len(pending),
    }


def main() -> int:
    _wait_for_database("gateway", GATEWAY_DATABASE_DSN)
    _wait_for_database("knowledge-base", KB_DATABASE_DSN)

    gateway_migrations = _apply_migrations(GATEWAY_DATABASE_DSN, GATEWAY_MIGRATIONS_DIR)
    kb_migrations = _apply_migrations(KB_DATABASE_DSN, KB_MIGRATIONS_DIR)

    KB_BLOB_ROOT.mkdir(parents=True, exist_ok=True)
    storage = ObjectStorageClient()
    storage.ensure_bucket()
    vector_store = _wait_for_vector_store()

    print(
        json.dumps(
            {
                "status": "ok",
                "gateway_migrations": gateway_migrations,
                "kb_migrations": kb_migrations,
                "blob_root": str(KB_BLOB_ROOT),
                "bucket": storage.settings.bucket,
                "vector_store": vector_store,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
