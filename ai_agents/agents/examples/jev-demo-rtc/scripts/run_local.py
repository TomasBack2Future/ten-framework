"""Read the private certificate without copying it into a graph or client asset."""

import os
from pathlib import Path
import re


def main():
    if not os.environ.get("AGORA_APP_CERTIFICATE"):
        certificate_file = os.environ.get("AGORA_APP_CERTIFICATE_FILE")
        if not certificate_file:
            raise SystemExit(
                "Set AGORA_APP_CERTIFICATE_FILE to the private .secret/agora file"
            )
        value = Path(certificate_file).read_text().strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", value):
            raise SystemExit(
                "Certificate file must contain one 32-character hex value"
            )
        os.environ["AGORA_APP_CERTIFICATE"] = value
    os.environ.setdefault("AGORA_APP_ID", "518383bde9d44172961da1595e982189")
    os.environ.setdefault(
        "JEV_GRAPH_COMMAND", ".venv/bin/python scripts/run_graph.py"
    )
    os.environ["JEV_MODE"] = "live"
    os.chdir(Path(__file__).resolve().parents[1])
    os.execvp("node", ["node", "web/server.mjs"])


if __name__ == "__main__":
    main()
