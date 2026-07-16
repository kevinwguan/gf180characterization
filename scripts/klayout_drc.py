#!/usr/bin/env python3
"""Run the pinned GF180 raw KLayout deck with its native option contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from signoff_env import NIX_STORE, nix_tool, verify_nix_shell


DISABLED_TABLES = {"antenna", "cup", "density"}
SCAFFOLDING_TABLES = {"layers_def", "main", "tail"}
EXCLUDED_TABLES = DISABLED_TABLES | SCAFFOLDING_TABLES
VARIANTS = {
    "C": {"metal_top": "9K", "metal_level": "5LM", "mim_option": "B"},
    "D": {"metal_top": "11K", "metal_level": "5LM", "mim_option": "B"},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def included_tables(source_deck: Path) -> list[str]:
    include = re.compile(r"^# %include rule_decks/([a-zA-Z0-9_]+)\.drc$")
    deck_tables = [
        match.group(1)
        for line in source_deck.read_text().splitlines()
        if (match := include.match(line))
    ]
    if "cup" not in deck_tables:
        raise SystemExit("pinned GF180 raw deck no longer contains the CUP table")
    tables = sorted(set(deck_tables).difference(EXCLUDED_TABLES))
    required = {"comp", "contact", "geom", "metal1", "metal5", "via1", "via4"}
    if missing := required.difference(tables):
        raise SystemExit(f"pinned GF180 deck is missing required tables: {missing}")
    return tables


def summarize(report: Path) -> tuple[dict[str, int], int]:
    root = ET.parse(report).getroot()
    counts = {
        category.findtext("name", default=""): 0
        for category in root.findall("./categories//category")
    }
    violations = Counter(
        item.findtext("category", default="").strip("'")
        for item in root.findall("./items/item")
    )
    counts.update(violations)
    return dict(sorted(counts.items())), sum(violations.values())


def build_filtered_deck(source_deck: Path, run_dir: Path) -> Path:
    """Copy the precheck's raw deck while removing explicitly skipped tables."""
    include = re.compile(r"^(# %include rule_decks/)([a-zA-Z0-9_]+)(\.drc)$")
    filtered: list[str] = []
    for line in source_deck.read_text().splitlines(keepends=True):
        match = include.match(line.rstrip("\n"))
        if match and match.group(2) in DISABLED_TABLES:
            filtered.append(
                f"# gf180characterization excluded {match.group(2)}.drc\n"
            )
        else:
            filtered.append(line)

    rule_decks = run_dir / "rule_decks"
    rule_decks.symlink_to(source_deck.parent / "rule_decks", target_is_directory=True)
    deck = run_dir / "gf180mcu.filtered.drc"
    deck.write_text("".join(filtered))
    return deck


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--top", required=True)
    parser.add_argument("--pdk-root", required=True, type=Path)
    parser.add_argument("--pdk-commit", required=True)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--variant", choices=VARIANTS, default="D")
    parser.add_argument("--run-mode", choices=("flat", "deep"), default="deep")
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()

    verify_nix_shell()
    python = Path(sys.executable).resolve()
    if not python.is_relative_to(NIX_STORE):
        raise SystemExit(f"refusing host Python for KLayout sign-off: {python}")
    source = args.input.resolve()
    if not source.is_file():
        raise SystemExit(f"KLayout DRC input does not exist: {source}")
    if args.threads < 1:
        raise SystemExit("KLayout DRC threads must be positive")

    pdk_root = args.pdk_root.resolve()
    drc_dir = pdk_root / "gf180mcuD/libs.tech/klayout/tech/drc"
    source_deck = drc_dir / "gf180mcu.drc"
    if not source_deck.is_file():
        raise SystemExit(f"pinned GF180 KLayout deck is missing: {source_deck}")
    git = nix_tool("git")
    klayout = nix_tool("klayout")
    actual_pdk_commit = subprocess.run(
        [str(git), "-C", str(pdk_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_pdk_commit != args.pdk_commit:
        raise SystemExit(
            f"KLayout PDK is at {actual_pdk_commit}, expected {args.pdk_commit}"
        )

    run_dir = args.run_dir.resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        raise SystemExit(f"refusing to mix KLayout evidence in non-empty {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    tables = included_tables(source_deck)
    deck = build_filtered_deck(source_deck, run_dir)
    report = run_dir / "drc.klayout.lyrdb"
    variant = VARIANTS[args.variant]
    command = [
        str(klayout),
        "-b",
        "-r",
        str(deck),
        "-rd",
        f"thr={args.threads}",
        "-rd",
        f"metal_top={variant['metal_top']}",
        "-rd",
        f"mim_option={variant['mim_option']}",
        "-rd",
        f"metal_level={variant['metal_level']}",
        "-rd",
        "verbose=false",
        "-rd",
        "feol=true",
        "-rd",
        "beol=true",
        "-rd",
        "offgrid=true",
        "-rd",
        "conn_drc=false",
        "-rd",
        "density=false",
        "-rd",
        "split_deep=false",
        "-rd",
        "slow_via=false",
        "-rd",
        f"topcell={args.top}",
        "-rd",
        f"input={source}",
        "-rd",
        f"report={report}",
        "-rd",
        f"run_mode={args.run_mode}",
        "-rd",
        "table_name=main",
    ]
    (run_dir / "COMMANDS").write_text(shlex.join(command) + "\n")

    log_path = run_dir / "klayout-drc.log"
    completed = False
    with log_path.open("w") as log:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
            completed |= "main DRC Total Run time" in line
        returncode = process.wait()

    if returncode != 0 or not completed:
        raise SystemExit(
            f"GF180 KLayout deck exited {returncode} before its completion "
            f"marker; see {log_path}"
        )
    if not report.is_file():
        raise SystemExit(f"GF180 KLayout deck did not produce {report}")
    counts, total = summarize(report)
    configuration = {
        "variant": args.variant,
        **variant,
        "run_mode": args.run_mode,
        "threads": args.threads,
        "feol": True,
        "beol": True,
        "offgrid": True,
        "connectivity": False,
        "disabled_tables": sorted(DISABLED_TABLES),
        "scaffolding_tables": sorted(SCAFFOLDING_TABLES),
        "rule_tables": tables,
    }
    result = {
        "input": str(source),
        "input_sha256": sha256(source),
        "top": args.top,
        "pdk_commit": actual_pdk_commit,
        "klayout": str(klayout),
        "source_deck": str(source_deck),
        "source_deck_sha256": sha256(source_deck),
        "deck": str(deck),
        "deck_generation": "pinned raw gf180mcu.drc with disabled includes removed",
        "deck_exit_code": returncode,
        "configuration": configuration,
        "rule_category_count": len(counts),
        "violations": counts,
        "total": total,
    }
    (run_dir / "drc.klayout.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"KLayout DRC rule categories: {len(counts)}")
    print(f"KLayout DRC total markers: {total}")

    raise SystemExit(1 if total else 0)


if __name__ == "__main__":
    main()
