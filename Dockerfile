# DealFinder production image: the API runs from it on Cloud Run.
# Two stages. The build stage installs the core dependencies (no dev, torch,
# mlflow or prefect extras) and bakes the embedding model in, so a cold start
# never downloads it. The runtime stage copies only what the service needs and
# runs as a non-root user. The app runs from its source in /app, so the venv
# holds dependencies only.
FROM python:3.11-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src
# Neither heavy layer depends on the source, so a code change rebuilds only the
# small COPY layers below and the registry keeps one copy of these across deploys.
# The dependencies, read from pyproject.toml: this layer changes only when they do.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
 && pip install --no-cache-dir -r requirements.txt
# The embedding model, by the name dealfinder/embed.py loads (test_deploy pins it).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')"

FROM python:3.11-slim
ENV PATH=/opt/venv/bin:$PATH
ENV DEALFINDER_MODEL_DIR=/opt/models HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=10001 /opt/models /opt/models
# The app reads data/ relative to the package, so the source tree is the one that runs.
COPY dealfinder/ dealfinder/
COPY data/ data/
USER 10001
EXPOSE 8000
# The CMD must match the ASGI app in dealfinder/serve.py (test_deploy guards this).
# Cloud Run sets PORT. Locally it defaults to 8000.
CMD ["sh", "-c", "exec uvicorn dealfinder.serve:app --host 0.0.0.0 --port ${PORT:-8000}"]
