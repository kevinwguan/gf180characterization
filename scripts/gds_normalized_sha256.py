#!/usr/bin/env python3
"""Hash GDSII records while ignoring library and structure timestamps."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


TIMESTAMP_RECORD_TYPES = {0x01, 0x05}  # BGNLIB, BGNSTR


def normalized_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while header := stream.read(4):
            if len(header) != 4:
                raise ValueError(f"{path}: truncated GDS record header")
            length = int.from_bytes(header[:2], "big")
            if length < 4:
                raise ValueError(f"{path}: invalid GDS record length {length}")
            payload = stream.read(length - 4)
            if len(payload) != length - 4:
                raise ValueError(f"{path}: truncated GDS record payload")
            if header[2] in TIMESTAMP_RECORD_TYPES:
                payload = bytes(len(payload))
            digest.update(header)
            digest.update(payload)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.gds:
        print(f"{normalized_sha256(path)}  {path}")


if __name__ == "__main__":
    main()
