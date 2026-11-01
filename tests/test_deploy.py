"""Deploy config and code must agree — a common source of "works locally, 502 in
prod". These cheap checks keep the Dockerfile CMD, the health check, and the ASGI
app in sync."""
import importlib
from pathlib import Path


def test_asgi_app_is_importable():
    mod = importlib.import_module("dealfinder.serve")
    assert hasattr(mod, "app")


def test_dockerfile_cmd_matches_the_app():
    df = Path("Dockerfile").read_text()
    assert "dealfinder.serve:app" in df    # the CMD targets the real app
    assert "uvicorn" in df


def test_healthcheck_path_exists_in_deploy_config():
    render = Path("render.yaml").read_text()
    assert "/healthz" in render             # and /healthz is a real route (test_serve)


def test_dockerfile_is_production_shaped():
    df = Path("Dockerfile").read_text()
    users = [line.split()[1] for line in df.splitlines() if line.startswith("USER ")]
    assert users and users[-1] not in ("root", "0")
    assert "${PORT:-8000}" in df
    assert "DEALFINDER_MODEL_DIR=/opt/models" in df and "HF_HUB_OFFLINE=1" in df


def test_image_excludes_dev_trees():
    ignored = Path(".dockerignore").read_text().split()
    assert {"frontend/", "edge/", "deploy/", "tests/", "notebooks/", ".env"} <= set(ignored)


def test_heavy_layers_do_not_depend_on_the_source():
    # Every deploy stored a fresh ~300 MB copy of the dependencies and the model
    # (live: two images = 595,730,597 bytes, over the free 0.5 GB), because both
    # layers came after `COPY dealfinder/`. They now come first, so a code change
    # rebuilds only the small source layers.
    from dealfinder import embed

    df = Path("Dockerfile").read_text()
    build = df.split("\nFROM ", 2)[1]
    assert "pip install" in build and "TextEmbedding(" in build
    assert "COPY dealfinder/" not in build and "COPY data/" not in build
    assert "pip install --no-cache-dir ." not in df   # the app runs from /app, the venv holds dependencies only
    assert f"TextEmbedding('{embed._MODEL_NAME}'" in build   # the baked model is the one embed.py loads
