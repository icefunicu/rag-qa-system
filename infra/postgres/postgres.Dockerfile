FROM postgres:16

COPY init/000_dual_kernel_bootstrap.sh /docker-entrypoint-initdb.d/000_dual_kernel_bootstrap.sh
