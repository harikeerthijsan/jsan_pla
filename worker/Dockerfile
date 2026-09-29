FROM condaforge/miniforge3:latest
WORKDIR /app
COPY api/requirements.txt /app/requirements.txt
RUN mamba install --yes --channel conda-forge "python=3.12" "pdal=2.10.2" "gdal=3.13.3" "libsqlite>=3.51.0" && mamba clean -afy && pip install --no-cache-dir -r /app/requirements.txt
COPY api /app
ENV PYTHONUNBUFFERED=1
CMD ["python","worker.py"]
