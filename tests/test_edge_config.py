"""edge/wrangler.jsonc: before launch, every deploy reaches only the beta host."""
import json
import re
from pathlib import Path

RAW = Path("edge/wrangler.jsonc").read_text()
CONFIG = json.loads(re.sub(r"(?m)^\s*//.*$", "", RAW))


def test_prelaunch_deploys_reach_only_the_beta_host():
    # The old dev UI sat on the launch hostname, reachable by anyone, from the first
    # deploy. Until Plan 8 adds a production env, the only config is staging.
    assert CONFIG["name"] == "dealfinder-edge-staging"
    assert CONFIG["routes"] == [{"pattern": "deals.beta.cloudcodetree.com", "custom_domain": True}]
    assert CONFIG["vars"]["LAUNCHED"] == "false"
    assert "env" not in CONFIG
    assert '"deals.cloudcodetree.com"' not in RAW
