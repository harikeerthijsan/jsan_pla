FROM condaforge/miniforge3:25.3.1-0
WORKDIR /app
COPY api/requirements.txt /app/requirements.txt
RUN mamba create --yes --name pla --channel conda-forge --strict-channel-priority \
        "python=3.12" "pdal=2.10.2" "gdal=3.13.3" "libsqlite>=3.51.0,<4" \
    && /opt/conda/envs/pla/bin/python -m pip install --no-cache-dir -r /app/requirements.txt \
    && /opt/conda/envs/pla/bin/python -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 38, 0), sqlite3.sqlite_version" \
    && /opt/conda/envs/pla/bin/gdalinfo --version \
    && /opt/conda/envs/pla/bin/pdal --drivers > /dev/null \
    && mamba clean --all --yes
COPY api /app
ENV PATH=/opt/conda/envs/pla/bin:$PATH \
    PDAL_BIN=/opt/conda/envs/pla/bin/pdal \
    PYTHONUNBUFFERED=1
CMD ["python","worker.py"]
