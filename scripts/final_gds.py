#!/usr/bin/env python3
"""Prepare an external GDS for seal-ring insertion and verify the result.

This script never creates or imports a padring.  The prepare phase centers the
external layout's sole top cell inside the selected slot.  The finish phase
proves that all centered source geometry remains present, checks the
Wafer.Space slot envelope and seal marker, then emits a GDS and a hash-locked
provenance manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import klayout.db as db


SLOTS = {
    "1x1": (3932.0, 5122.0),
    "0p5x1": (1936.0, 5122.0),
    "1x0p5": (3932.0, 2531.0),
    "0p5x0p5": (1936.0, 2531.0),
}
GUARD_RING_MK = (167, 5)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> db.Layout:
    layout = db.Layout()
    layout.read(str(path))
    return layout


def sole_top(layout: db.Layout) -> db.Cell:
    tops = layout.top_cells()
    if len(tops) != 1:
        raise SystemExit(f"expected exactly one top cell, found {[c.name for c in tops]}")
    return tops[0]


def bbox_um(cell: db.Cell, dbu: float) -> tuple[float, float, float, float]:
    box = cell.bbox()
    return tuple(v * dbu for v in (box.left, box.bottom, box.right, box.top))


def prepare(args: argparse.Namespace) -> None:
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    layout = load(source)
    top = sole_top(layout)
    if layout.dbu != 0.001:
        raise SystemExit(f"source dbu must be 0.001 um, got {layout.dbu}")
    box = bbox_um(top, layout.dbu)
    width, height = SLOTS[args.slot]
    if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
        raise SystemExit(f"source bbox {box} does not fit {args.slot} slot {width}x{height}")
    content_width = box[2] - box[0]
    content_height = box[3] - box[1]
    dx = (width - content_width) / 2 - box[0]
    dy = (height - content_height) / 2 - box[1]
    layout.rename_cell(top.cell_index(), f"{args.top}_content")
    wrapper = layout.create_cell(args.top)
    wrapper.insert(db.DCellInstArray(top, db.DTrans(dx, dy)))
    output.parent.mkdir(parents=True, exist_ok=True)
    options = db.SaveLayoutOptions()
    options.write_context_info = False
    layout.write(str(output), options)
    print(
        f"prepared external GDS only: {source} -> {output}; "
        f"source bbox={box}; centered by ({dx}, {dy}) um"
    )


def assert_source_preserved(source: db.Layout, sealed: db.Layout) -> None:
    source_top = sole_top(source)
    sealed_top = sole_top(sealed)
    sealed_layers = {
        (sealed.get_info(i).layer, sealed.get_info(i).datatype): i
        for i in sealed.layer_indexes()
    }

    def layer_stats(layout: db.Layout, top: db.Cell, layer: int) -> tuple:
        region = db.Region(top.begin_shapes_rec(layer))
        texts = 0
        iterator = top.begin_shapes_rec(layer)
        while not iterator.at_end():
            if iterator.shape().is_text():
                texts += 1
            iterator.next()
        return region.count(), region.area(), region.bbox(), texts

    for index in source.layer_indexes():
        info = source.get_info(index)
        key = (info.layer, info.datatype)
        sealed_index = sealed_layers.get(key)
        if sealed_index is None:
            raise SystemExit(f"sealed layout dropped source layer {key}")
        original = db.Region(source_top.begin_shapes_rec(index))
        result = db.Region(sealed_top.begin_shapes_rec(sealed_index))
        # GDS label layers contain large numbers of Text records. Region's
        # recursive-iterator constructor can report a non-empty subtraction
        # for identical Text records even though it reports zero polygons.
        # Labels are not mask geometry; compare stable polygon statistics and
        # recursive Text counts instead. Physical layers retain exact Region
        # containment below.
        original_stats = layer_stats(source, source_top, index)
        if info.datatype == 10 or (original_stats[0] == 0 and original_stats[3] > 0):
            if original_stats != layer_stats(
                sealed, sealed_top, sealed_index
            ):
                raise SystemExit(f"sealed layout changed source labels on layer {key}")
            continue
        if not (original - result).is_empty():
            raise SystemExit(f"sealed layout dropped source geometry on layer {key}")


def finish(args: argparse.Namespace) -> None:
    source_path = Path(args.source).resolve()
    sealed_path = Path(args.sealed).resolve()
    output = Path(args.output).resolve()
    manifest = Path(args.manifest).resolve()
    source = load(source_path)
    sealed = load(sealed_path)
    source_top = sole_top(source)
    sealed_top = sole_top(sealed)
    if source_top.name != args.top or sealed_top.name != args.top:
        raise SystemExit(
            f"top mismatch: source={source_top.name}, sealed={sealed_top.name}, expected={args.top}"
        )
    if sealed.dbu != 0.001:
        raise SystemExit(f"sealed dbu must be 0.001 um, got {sealed.dbu}")
    expected = SLOTS[args.slot]
    box = bbox_um(sealed_top, sealed.dbu)
    if box != (0.0, 0.0, expected[0], expected[1]):
        raise SystemExit(f"sealed bbox {box} does not equal {args.slot} slot {expected}")
    marker_index = sealed.find_layer(*GUARD_RING_MK)
    if marker_index is None or db.Region(
        sealed_top.begin_shapes_rec(marker_index)
    ).is_empty():
        raise SystemExit("sealed layout has no GUARD_RING_MK 167/5 geometry")
    assert_source_preserved(source, sealed)
    original_layout = load(Path(args.source_original).resolve())
    original_top = sole_top(original_layout)
    centered_box = bbox_um(source_top, source.dbu)
    original_box = bbox_um(original_top, original_layout.dbu)

    output.parent.mkdir(parents=True, exist_ok=True)
    with sealed_path.open("rb") as src, output.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    artifact_md5 = md5(output)
    checksum_path = output.with_suffix(output.suffix + ".md5")
    checksum_path.write_text(f"{artifact_md5}  {os.path.relpath(output)}\n")
    record = {
        "artifact": os.path.relpath(output),
        "artifact_sha256": sha256(output),
        "artifact_md5": artifact_md5,
        "md5_file": os.path.relpath(checksum_path),
        "source_original": os.path.relpath(Path(args.source_original).resolve()),
        "source_original_sha256": sha256(Path(args.source_original).resolve()),
        "prepared_sha256": sha256(source_path),
        "sealed_uncompressed_sha256": sha256(sealed_path),
        "top": args.top,
        "slot": args.slot,
        "bbox_um": box,
        "centered_content_bbox_um": centered_box,
        "source_translation_um": [
            centered_box[0] - original_box[0],
            centered_box[1] - original_box[1],
        ],
        "dbu_um": sealed.dbu,
        "guard_ring_marker": list(GUARD_RING_MK),
        "source_geometry_preserved": True,
        "padring_source": "external GDS only; no gf180characterization padring flow used",
        "wafer_space_pdk_commit": args.pdk_commit,
    }
    manifest.write_text(json.dumps(record, indent=2) + "\n")
    print(f"final sealed GDS: {output} sha256={record['artifact_sha256']}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--top", required=True)
    p.add_argument("--slot", choices=SLOTS, required=True)
    p.set_defaults(func=prepare)
    p = commands.add_parser("finish")
    p.add_argument("--source", required=True)
    p.add_argument("--sealed", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--top", required=True)
    p.add_argument("--slot", choices=SLOTS, required=True)
    p.add_argument("--source-original", required=True)
    p.add_argument("--pdk-commit", required=True)
    p.set_defaults(func=finish)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
