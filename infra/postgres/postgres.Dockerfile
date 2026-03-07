FROM postgres:16

COPY init /docker-entrypoint-initdb.d
