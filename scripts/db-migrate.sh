#!/bin/sh
set -eu

POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-rag}"
POSTGRES_USER="${POSTGRES_USER:-rag}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-rag}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"
MIGRATIONS_TABLE="${MIGRATIONS_TABLE:-schema_migrations}"
MAX_ATTEMPTS="${DB_MIGRATE_MAX_ATTEMPTS:-60}"
RETRY_SECONDS="${DB_MIGRATE_RETRY_SECONDS:-2}"

export PGPASSWORD="$POSTGRES_PASSWORD"

log() {
    printf '%s\n' "[db-migrate] $*"
}

psql_cmd() {
    psql \
        --host "$POSTGRES_HOST" \
        --port "$POSTGRES_PORT" \
        --username "$POSTGRES_USER" \
        --dbname "$POSTGRES_DB" \
        --set ON_ERROR_STOP=1 \
        "$@"
}

wait_for_postgres() {
    attempt=1
    while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
        if pg_isready --host "$POSTGRES_HOST" --port "$POSTGRES_PORT" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" >/dev/null 2>&1; then
            return 0
        fi

        log "waiting for PostgreSQL (${attempt}/${MAX_ATTEMPTS})"
        attempt=$((attempt + 1))
        sleep "$RETRY_SECONDS"
    done

    log "PostgreSQL is not ready after ${MAX_ATTEMPTS} attempts"
    return 1
}

escape_sql_literal() {
    printf '%s' "$1" | sed "s/'/''/g"
}

compute_checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
        return
    fi

    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
        return
    fi

    cksum "$1" | awk '{print $1 ":" $2}'
}

ensure_migration_table() {
    psql_cmd <<SQL
CREATE TABLE IF NOT EXISTS ${MIGRATIONS_TABLE} (
    filename TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL
}

get_recorded_checksum() {
    file_name_escaped="$(escape_sql_literal "$1")"
    psql_cmd --tuples-only --no-align --command "SELECT checksum FROM ${MIGRATIONS_TABLE} WHERE filename = '${file_name_escaped}';" | tr -d '[:space:]'
}

record_migration() {
    file_name_escaped="$(escape_sql_literal "$1")"
    checksum_escaped="$(escape_sql_literal "$2")"
    psql_cmd --command "INSERT INTO ${MIGRATIONS_TABLE} (filename, checksum) VALUES ('${file_name_escaped}', '${checksum_escaped}');" >/dev/null
}

list_migration_files() {
    find "$MIGRATIONS_DIR" -maxdepth 1 -type f -name '*.sql' | sort
}

apply_migration() {
    file_path="$1"
    file_name="$(basename "$file_path")"
    checksum="$(compute_checksum "$file_path")"
    recorded_checksum="$(get_recorded_checksum "$file_name")"

    if [ -n "$recorded_checksum" ]; then
        if [ "$recorded_checksum" = "$checksum" ]; then
            log "skip ${file_name} (already applied)"
            return 0
        fi

        log "checksum mismatch for ${file_name}. Existing migration files must be immutable."
        return 1
    fi

    log "apply ${file_name}"
    psql_cmd --single-transaction --file "$file_path"
    record_migration "$file_name" "$checksum"
}

main() {
    log "connecting to ${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
    wait_for_postgres
    ensure_migration_table

    migration_files="$(list_migration_files)"
    if [ -z "$migration_files" ]; then
        log "no migration files found in ${MIGRATIONS_DIR}"
        return 0
    fi

    printf '%s\n' "$migration_files" | while IFS= read -r file_path; do
        apply_migration "$file_path"
    done

    log "migrations complete"
}

main "$@"
