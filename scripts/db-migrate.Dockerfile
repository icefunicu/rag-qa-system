FROM postgres:16

COPY scripts/db-migrate.sh /usr/local/bin/db-migrate.sh
COPY infra/postgres/init /migrations

RUN chmod 0755 /usr/local/bin/db-migrate.sh
