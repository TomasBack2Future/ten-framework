#!/usr/bin/env python3
"""Export one preserved demo session without modifying its source files."""

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path


def export_session(root, session_id, output):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", session_id):
        raise ValueError("invalid session id")
    directory = Path(root) / session_id
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("session evidence directory unavailable")
    files = sorted(directory.iterdir())
    manifest = {
        "schema": "jev.evidence.export.v1",
        "session_id": session_id,
        "files": [],
    }
    with os.fdopen(
        os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    ) as destination:
        with tarfile.open(fileobj=destination, mode="w:gz") as archive:
            for file in files:
                if file.is_symlink() or not file.is_file():
                    raise ValueError("unexpected evidence entry")
                digest = hashlib.sha256()
                with file.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                size = file.stat().st_size
                manifest["files"].append(
                    {
                        "name": file.name,
                        "bytes": size,
                        "sha256": digest.hexdigest(),
                    }
                )
                info = tarfile.TarInfo(session_id + "/" + file.name)
                info.size = size
                info.mode = 0o600
                with file.open("rb") as source:
                    archive.addfile(info, source)
            content = (json.dumps(manifest, indent=2) + "\n").encode()
            info = tarfile.TarInfo(session_id + "/manifest.json")
            info.size = len(content)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(content))
    Path(output).chmod(0o600)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = export_session(args.root, args.session, args.output)
    print(
        json.dumps(
            {"session_id": result["session_id"], "files": len(result["files"])}
        )
    )


if __name__ == "__main__":
    main()
