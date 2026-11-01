"""Where configuration comes from in each environment.

Locally the course reads `.env` (see the package docstring). In production
there is no `.env`: Cloud Run passes one Secret Manager secret as the env var
DEALFINDER_SECRETS_JSON, a JSON object of string values, and load_secrets()
expands it into ordinary environment variables at startup. One secret keeps the
project inside Secret Manager's free version allowance.
"""

import json
import os


def is_production() -> bool:
    return os.getenv("DEALFINDER_ENV") == "production"


def load_secrets() -> None:
    """Expand DEALFINDER_SECRETS_JSON into os.environ, never overriding a set variable.

    A variable set directly on the service wins over the blob, so one key can be
    overridden without a new secret version. Error text never includes a value."""
    raw = os.getenv("DEALFINDER_SECRETS_JSON")
    if not raw:
        return
    try:
        blob = json.loads(raw)
    except ValueError:
        blob = None
    if not isinstance(blob, dict) or not all(isinstance(v, str) for v in blob.values()):
        raise RuntimeError("DEALFINDER_SECRETS_JSON is not a JSON object") from None
    for key, value in blob.items():
        os.environ.setdefault(key, value)
