FROM condaforge/miniforge3:26.7.2-0 AS geospatial

WORKDIR /app

COPY api/requirements.txt /tmp/requirements.txt
RUN mamba create --yes --name pla --channel conda-forge --strict-channel-priority \
        "python=3.12" "pdal=2.10.2" "gdal=3.13.3" "libsqlite>=3.51.0,<4" \
        "setuptools>=78.1.1" "msgpack-python>=1.2.1" \
    && /opt/conda/envs/pla/bin/python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && /opt/conda/envs/pla/bin/python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 38, 0), sqlite3.sqlite_version" \
    && /opt/conda/envs/pla/bin/gdalinfo --version \
    && /opt/conda/envs/pla/bin/pdal --drivers > /dev/null \
    && mamba clean --all --yes

FROM ubuntu:24.04

RUN apt-get update \
    && apt-get upgrade --yes \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=geospatial /opt/conda/envs/pla /opt/conda/envs/pla

COPY api/app /app/api/app
COPY api/seed /app/api/seed
COPY api/alembic.ini /app/api/alembic.ini
COPY api/migrations /app/api/migrations
COPY api/worker.py /app/api/worker.py
COPY api/railway_entrypoint.py /app/api/railway_entrypoint.py
COPY web /app/web

ENV APP_ENV=production \
    APP_VERSION=3.4.1-operational \
    PATH=/opt/conda/envs/pla/bin:$PATH \
    PDAL_BIN=/opt/conda/envs/pla/bin/pdal \
    PYTHONPATH=/app/api \
    PYTHONUNBUFFERED=1 \
    STORAGE_MODE=s3 \
    WEB_ROOT=/app/web

WORKDIR /app/api
EXPOSE 8000

CMD ["python", "railway_entrypoint.py"]
