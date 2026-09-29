FROM condaforge/miniforge3:25.3.1-0

WORKDIR /app

COPY api/requirements.txt /tmp/requirements.txt
RUN mamba install --yes --channel conda-forge "python=3.12" "pdal=2.10.2" "gdal=3.13.3" "libsqlite>=3.51.0" \
    && mamba clean --all --yes \
    && python -m pip install --no-cache-dir -r /tmp/requirements.txt

COPY api/app /app/api/app
COPY api/seed /app/api/seed
COPY api/worker.py /app/api/worker.py
COPY api/railway_entrypoint.py /app/api/railway_entrypoint.py
COPY web /app/web

ENV APP_ENV=production \
    PDAL_BIN=pdal \
    PYTHONPATH=/app/api \
    PYTHONUNBUFFERED=1 \
    STORAGE_MODE=s3 \
    WEB_ROOT=/app/web

WORKDIR /app/api
EXPOSE 8000

CMD ["python", "railway_entrypoint.py"]
