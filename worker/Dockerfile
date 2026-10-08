FROM condaforge/miniforge3:26.7.2-0 AS geospatial
WORKDIR /app
COPY api/requirements.txt /app/requirements.txt
RUN mamba create --yes --name pla --channel conda-forge --strict-channel-priority \
        "python=3.12" "pdal=2.10.2" "gdal=3.13.3" "libsqlite>=3.51.0,<4" "untwine=1.5.1" \
        "setuptools>=78.1.1" "msgpack-python>=1.2.1" \
    && /opt/conda/envs/pla/bin/python -m pip install --no-cache-dir -r /app/requirements.txt \
    && /opt/conda/envs/pla/bin/python -c "import msgpack, setuptools; assert tuple(map(int, setuptools.__version__.split('.')[:3])) >= (78, 1, 1); assert msgpack.version >= (1, 2, 1)" \
    && /opt/conda/envs/pla/bin/python -m pip check \
    && rm -rf /opt/conda/envs/pla/lib/python3.12/site-packages/pip \
        /opt/conda/envs/pla/lib/python3.12/site-packages/pip-*.dist-info \
        /opt/conda/envs/pla/bin/pip /opt/conda/envs/pla/bin/pip3 \
        /opt/conda/envs/pla/bin/pip3.12 \
    && rm -f /opt/conda/envs/pla/conda-meta/pip-*.json \
    && /opt/conda/envs/pla/bin/python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 38, 0), sqlite3.sqlite_version" \
    && /opt/conda/envs/pla/bin/gdalinfo --version \
    && /opt/conda/envs/pla/bin/pdal --drivers > /dev/null \
    && test -x /opt/conda/envs/pla/bin/untwine \
    && mamba clean --all --yes

FROM ubuntu:24.04
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade --yes \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=geospatial /opt/conda/envs/pla /opt/conda/envs/pla
COPY api /app
ENV PATH=/opt/conda/envs/pla/bin:$PATH \
    PDAL_BIN=/opt/conda/envs/pla/bin/pdal \
    UNTWINE_BIN=/opt/conda/envs/pla/bin/untwine \
    PYTHONUNBUFFERED=1
CMD ["python","worker.py"]
