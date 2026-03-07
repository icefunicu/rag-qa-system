#!/bin/bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'EOSQL'
SELECT 'CREATE DATABASE novel_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'novel_app')\gexec

SELECT 'CREATE DATABASE kb_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'kb_app')\gexec
EOSQL
