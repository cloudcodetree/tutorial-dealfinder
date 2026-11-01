"""DealFinder — search an item, aggregate live offers, rank by value.

Importing the package loads `.env` from the current directory (or any parent)
so API keys documented in the course work for every entry point — scripts,
uvicorn, pytest — without shell exports. Real environment variables win over
the file (load_dotenv's default), so deploys that inject env vars directly
(Kubernetes secrets, CI) are unaffected.

`.env` loads only outside production. With DEALFINDER_ENV=production the
service's one JSON secret is expanded instead (`settings.load_secrets`), and a
stray `.env` on a host or in an image is never read.
"""

from . import settings

settings.load_secrets()

if not settings.is_production():
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - dotenv is a hard dep; guard for slim installs
        pass
