#!/usr/bin/env python3
"""Prepare an external GDS for seal-ring insertion and verify the result.

This script never creates or imports a padring.  The prepare phase applies the
validated GF180 corner repairs and centers the external layout's sole top cell
inside the selected slot.  The finish phase proves that all centered source
geometry remains present, checks the Wafer.Space slot envelope and seal marker,
then emits a GDS and a hash-locked provenance manifest.
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
METAL1 = (34, 0)
METAL5 = (81, 0)

# The Wafer.Space precheck flattens every cell matching ``*_CDNS_*`` before
# running Magic.  Flattening the foundry M4/M3 and M5/M4 via generators makes
# Magic split otherwise legal, fully enclosed 0.26 um via arrays into narrow
# tiles and report V3.1/V3.4 and V4.1/V4.4 false positives.  Keeping just these
# two generator families hierarchical avoids that importer artifact while the
# mask geometry remains exactly equivalent.
MAGIC_HIERARCHICAL_VIA_PREFIXES = ("M4_M3_CDNS_", "M5_M4_CDNS_")
MAGIC_HIERARCHICAL_VIA_REPLACEMENT = "_HIER_"

# The GF180 foundry corner cell contains three 0.28 um-deep Metal1 notches in
# a single, already-connected power rail.  Magic's full M1.2b rule requires
# 0.30 um spacing at these wide-metal notches.  Filling the rightmost 0.30 um
# of each notch removes the violations without connecting previously separate
# nets.  Coordinates are in the cell's 0.001 um database units.
GF180_CORNER_CELL = "gf180mcu_fd_io__cor"
GF180_CORNER_BBOX = db.Box(0, 0, 355160, 355160)
GF180_CORNER_M1_BRIDGES = (
    db.Box(128710, 165505, 129010, 165785),
    db.Box(128710, 164885, 129010, 165165),
    db.Box(190320, 103275, 190620, 103555),
)

# The two characterization bends were generated as smooth GDS polygons.  The
# GF180 deck permits only 0/45/90-degree Metal1 edges on a 0.005 um grid.  A
# minimal outward Manhattan cover on that exact grid preserves every original
# point and the routed topology while replacing only the exposed boundary.
KLAYOUT_MANHATTAN_GRID = 5
KLAYOUT_OVERLAY_MAX_POINTS = 180
KLAYOUT_BEND_SPECS = {
    "ts_bend": {
        "bbox": db.Box(-5250, -5250, 5250, 5250),
        "area": 15707866,
        "points": 124,
        "direct_shapes": 3,
    },
    "ts_bend_s": {
        "bbox": db.Box(-5500, -1400, 5500, 1400),
        "area": 11205917,
        "points": 198,
        "direct_shapes": 3,
    },
}

# The Metal5 gdsfactory logo has two staircase transitions where the pinned
# deck's wide-metal reconstruction touches the original boundary and emits
# MT.2b markers.  These 45-degree triangles remove only those two transitions;
# each shares two boundary segments with the same original logo polygon.
GDSFACTORY_LOGO_CELL = "gdsfactory_logo"
GDSFACTORY_LOGO_BBOX = db.Box(0, 0, 1759500, 138000)
GDSFACTORY_LOGO_TARGET = {
    "bbox": db.Box(211500, 1500, 348000, 136500),
    "area": 4108500000,
    "points": 206,
    "direct_shapes": 11,
}
GDSFACTORY_LOGO_M5_PATCHES = (
    ((285000, 12000), (286500, 12000), (286500, 13500)),
    ((285000, 126000), (286500, 124500), (286500, 126000)),
)


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


def _region_contains(region: db.Region, box: db.Box) -> bool:
    return (db.Region(box) - region).is_empty()


def _bridge_is_same_net(region: db.Region, bridge: db.Box) -> bool:
    """Prove both sides of a proposed bridge are already one polygon."""

    lower = db.Box(bridge.left, bridge.bottom - 1, bridge.right, bridge.bottom)
    upper = db.Box(bridge.left, bridge.top, bridge.right, bridge.top + 1)
    for polygon in region.each():
        connected = db.Region(polygon)
        if _region_contains(connected, lower) and _region_contains(connected, upper):
            return True
    return False


def _same_region(left: db.Region, right: db.Region) -> bool:
    return (left - right).is_empty() and (right - left).is_empty()


def _find_exact_polygon(
    cell: db.Cell, layer_index: int, spec: dict, description: str
) -> db.Polygon:
    shapes = list(cell.shapes(layer_index).each())
    if len(shapes) != spec["direct_shapes"]:
        raise SystemExit(
            f"unexpected {description} direct-shape count {len(shapes)}, "
            f"expected {spec['direct_shapes']}"
        )
    matches = []
    for shape in shapes:
        if not shape.is_polygon():
            continue
        polygon = shape.polygon
        if (
            polygon.bbox() == spec["bbox"]
            and polygon.area() == spec["area"]
            and polygon.num_points_hull() == spec["points"]
        ):
            matches.append(polygon)
    if len(matches) != 1:
        raise SystemExit(
            f"expected one exact {description} polygon, found {len(matches)}"
        )
    return matches[0]


def _outward_manhattan_cover(original: db.Region) -> db.Region:
    """Return the smallest horizontal-strip cover on the GF180 5 nm grid."""

    grid = KLAYOUT_MANHATTAN_GRID
    box = original.bbox()
    y0 = (box.bottom // grid) * grid
    y1 = -((-box.top) // grid) * grid
    cover = db.Region()
    for y in range(y0, y1, grid):
        strip = db.Region(db.Box(box.left - grid, y, box.right + grid, y + grid))
        for polygon in (original & strip).each():
            cut_box = polygon.bbox()
            x0 = (cut_box.left // grid) * grid
            x1 = -((-cut_box.right) // grid) * grid
            if x1 > x0:
                cover.insert(db.Box(x0, y, x1, y + grid))
    cover.merge()
    if not (original - cover).is_empty():
        raise SystemExit("Manhattan cover dropped original Metal1")
    for polygon in cover.each():
        for point in polygon.each_point_hull():
            if point.x % grid or point.y % grid:
                raise SystemExit(f"Manhattan cover contains off-grid point {point}")
        for edge in polygon.each_edge():
            if edge.p1.x != edge.p2.x and edge.p1.y != edge.p2.y:
                raise SystemExit(f"Manhattan cover contains non-orthogonal edge {edge}")
    return cover


def _bounded_overlay_pieces(cover: db.Region) -> list[db.Polygon]:
    reference = cover.dup()
    pieces = cover.break_polygons(KLAYOUT_OVERLAY_MAX_POINTS, 0)
    if not _same_region(reference, pieces):
        raise SystemExit("breaking the Metal1 overlay changed its geometry")
    result = list(pieces.each())
    if not result or any(
        polygon.num_points_hull() > KLAYOUT_OVERLAY_MAX_POINTS
        for polygon in result
    ):
        raise SystemExit("Metal1 overlay could not be bounded for GDS output")
    return result


def _logo_patch_region() -> db.Region:
    patches = db.Region()
    for coordinates in GDSFACTORY_LOGO_M5_PATCHES:
        polygon = db.Polygon([db.Point(x, y) for x, y in coordinates])
        for edge in polygon.each_edge():
            dx = abs(edge.p2.x - edge.p1.x)
            dy = abs(edge.p2.y - edge.p1.y)
            if dx and dy and dx != dy:
                raise SystemExit(f"logo patch contains non-45-degree edge {edge}")
        patches.insert(polygon)
    return patches


def apply_klayout_drc_repairs(layout: db.Layout) -> dict:
    """Add only source-preserving covers for the four KLayout rule classes."""

    present_bends = [
        name for name in KLAYOUT_BEND_SPECS if layout.cell(name) is not None
    ]
    logo = layout.cell(GDSFACTORY_LOGO_CELL)
    if not present_bends and logo is None:
        return {
            "manhattan_grid_um": KLAYOUT_MANHATTAN_GRID * layout.dbu,
            "bend_overlays": [],
            "bend_overlay_count": 0,
            "logo_cell": None,
            "logo_metal5_patches": [],
            "logo_metal5_patch_count": 0,
        }
    if layout.dbu != 0.001:
        raise SystemExit(f"KLayout repairs require 0.001 um dbu, got {layout.dbu}")

    bend_records = []
    metal1_index = layout.find_layer(*METAL1)
    if present_bends and metal1_index is None:
        raise SystemExit(f"KLayout bend repairs require Metal1 {METAL1}")
    for name in present_bends:
        cell = layout.cell(name)
        assert cell is not None and metal1_index is not None
        polygon = _find_exact_polygon(
            cell, metal1_index, KLAYOUT_BEND_SPECS[name], f"{name} Metal1"
        )
        before = db.Region(cell.shapes(metal1_index))
        before.merge()
        if before.count() != 1:
            raise SystemExit(f"{name} Metal1 is not one connected conductor")
        cover = _outward_manhattan_cover(db.Region(polygon))
        expected_additions = cover - before
        pieces = _bounded_overlay_pieces(cover)
        for piece in pieces:
            cell.shapes(metal1_index).insert(piece)
        after = db.Region(cell.shapes(metal1_index))
        after.merge()
        if not (before - after).is_empty():
            raise SystemExit(f"{name} overlay removed original Metal1")
        if not _same_region(after - before, expected_additions):
            raise SystemExit(f"{name} overlay added unexpected Metal1")
        if after.count() != 1:
            raise SystemExit(f"{name} overlay split the Metal1 conductor")
        bend_records.append(
            {
                "cell": name,
                "source_polygon_bbox": [
                    polygon.bbox().left,
                    polygon.bbox().bottom,
                    polygon.bbox().right,
                    polygon.bbox().top,
                ],
                "source_polygon_area_dbu2": polygon.area(),
                "added_area_dbu2": expected_additions.area(),
                "overlay_polygon_count": len(pieces),
                "overlay_max_points": max(
                    piece.num_points_hull() for piece in pieces
                ),
            }
        )

    logo_patches = []
    if logo is not None:
        if logo.bbox() != GDSFACTORY_LOGO_BBOX:
            raise SystemExit(
                f"unexpected {GDSFACTORY_LOGO_CELL} bbox {logo.bbox()}, "
                f"expected {GDSFACTORY_LOGO_BBOX}"
            )
        metal5_index = layout.find_layer(*METAL5)
        if metal5_index is None:
            raise SystemExit(f"logo repair requires Metal5 {METAL5}")
        _find_exact_polygon(
            logo,
            metal5_index,
            GDSFACTORY_LOGO_TARGET,
            f"{GDSFACTORY_LOGO_CELL} Metal5 target",
        )
        before = db.Region(logo.shapes(metal5_index))
        before.merge()
        if before.count() != GDSFACTORY_LOGO_TARGET["direct_shapes"]:
            raise SystemExit("unexpected connected-component count in Metal5 logo")
        patches = _logo_patch_region()
        combined = before + patches
        combined.merge()
        if combined.count() != before.count():
            raise SystemExit("logo patches connect previously separate Metal5 shapes")
        expected_additions = patches - before
        if expected_additions.area() != patches.area():
            raise SystemExit("logo patches unexpectedly overlap existing Metal5 area")
        for patch in patches.each():
            logo.shapes(metal5_index).insert(patch)
        after = db.Region(logo.shapes(metal5_index))
        after.merge()
        if not _same_region(after - before, expected_additions):
            raise SystemExit("logo repair added unexpected Metal5")
        logo_patches = [
            [[x, y] for x, y in coordinates]
            for coordinates in GDSFACTORY_LOGO_M5_PATCHES
        ]

    return {
        "manhattan_grid_um": KLAYOUT_MANHATTAN_GRID * layout.dbu,
        "bend_overlays": bend_records,
        "bend_overlay_count": len(bend_records),
        "logo_cell": GDSFACTORY_LOGO_CELL if logo is not None else None,
        "logo_metal5_patches": logo_patches,
        "logo_metal5_patch_count": len(logo_patches),
    }


def apply_magic_drc_repairs(layout: db.Layout) -> dict:
    """Apply narrowly scoped, fail-closed repairs for GF180 foundry corners."""

    renamed = []
    candidates = [
        cell
        for cell in layout.each_cell()
        if cell.name.startswith(MAGIC_HIERARCHICAL_VIA_PREFIXES)
    ]
    for cell in candidates:
        old_name = cell.name
        new_name = old_name.replace(
            "_CDNS_", MAGIC_HIERARCHICAL_VIA_REPLACEMENT, 1
        )
        if layout.cell(new_name) is not None:
            raise SystemExit(
                f"cannot preserve Magic via hierarchy: cell {new_name} already exists"
            )
        cell.name = new_name
        renamed.append([old_name, new_name])

    bridges = []
    corner = layout.cell(GF180_CORNER_CELL)
    if corner is not None:
        if layout.dbu != 0.001:
            raise SystemExit(
                f"GF180 corner repair requires 0.001 um dbu, got {layout.dbu}"
            )
        if corner.bbox() != GF180_CORNER_BBOX:
            raise SystemExit(
                f"unexpected {GF180_CORNER_CELL} bbox {corner.bbox()}, "
                f"expected {GF180_CORNER_BBOX}"
            )
        metal1_index = layout.find_layer(*METAL1)
        if metal1_index is None:
            raise SystemExit(f"{GF180_CORNER_CELL} has no Metal1 layer {METAL1}")
        before = db.Region(corner.begin_shapes_rec(metal1_index))
        before.merge()
        for bridge in GF180_CORNER_M1_BRIDGES:
            if not _bridge_is_same_net(before, bridge):
                raise SystemExit(
                    f"refusing Metal1 bridge {bridge}: its two sides are not "
                    "already connected in the foundry corner cell"
                )
            corner.shapes(metal1_index).insert(bridge)
            bridges.append(
                [bridge.left, bridge.bottom, bridge.right, bridge.top]
            )
        after = db.Region(corner.begin_shapes_rec(metal1_index))
        if not (before - after).is_empty():
            raise SystemExit("GF180 corner repair unexpectedly removed Metal1")
        allowed = db.Region()
        for bridge in GF180_CORNER_M1_BRIDGES:
            allowed.insert(bridge)
        if not ((after - before) - allowed).is_empty():
            raise SystemExit("GF180 corner repair added Metal1 outside bridge boxes")

    return {
        "hierarchical_via_cells_renamed": len(renamed),
        "hierarchical_via_cell_renames": renamed,
        "corner_cell": GF180_CORNER_CELL if corner is not None else None,
        "corner_metal1_bridges": bridges,
        "corner_metal1_bridge_count": len(bridges),
    }


def verify_magic_drc_repairs(original: db.Layout, repaired: db.Layout) -> dict:
    """Verify the hierarchy renames and bound all corner Metal1 additions."""

    expected_renames = []
    for cell in original.each_cell():
        if not cell.name.startswith(MAGIC_HIERARCHICAL_VIA_PREFIXES):
            continue
        new_name = cell.name.replace(
            "_CDNS_", MAGIC_HIERARCHICAL_VIA_REPLACEMENT, 1
        )
        expected_renames.append([cell.name, new_name])
        if repaired.cell(cell.name) is not None:
            raise SystemExit(f"prepared GDS retained flattened via name {cell.name}")
        if repaired.cell(new_name) is None:
            raise SystemExit(f"prepared GDS is missing renamed via cell {new_name}")

    original_corner = original.cell(GF180_CORNER_CELL)
    repaired_corner = repaired.cell(GF180_CORNER_CELL)
    if original_corner is None:
        if repaired_corner is not None:
            raise SystemExit(
                f"prepared GDS unexpectedly added corner cell {GF180_CORNER_CELL}"
            )
        return {
            "hierarchical_via_cells_renamed": len(expected_renames),
            "hierarchical_via_cell_renames": expected_renames,
            "corner_cell": None,
            "corner_metal1_bridges": [],
            "corner_metal1_bridge_count": 0,
        }
    if repaired_corner is None:
        raise SystemExit(f"prepared GDS dropped corner cell {GF180_CORNER_CELL}")
    if original.dbu != repaired.dbu or repaired.dbu != 0.001:
        raise SystemExit(
            "cannot compare GF180 corner repairs across mismatched database units"
        )
    if original_corner.bbox() != GF180_CORNER_BBOX:
        raise SystemExit(
            f"unexpected original {GF180_CORNER_CELL} bbox {original_corner.bbox()}"
        )
    if repaired_corner.bbox() != GF180_CORNER_BBOX:
        raise SystemExit(
            f"unexpected repaired {GF180_CORNER_CELL} bbox {repaired_corner.bbox()}"
        )

    original_m1_index = original.find_layer(*METAL1)
    repaired_m1_index = repaired.find_layer(*METAL1)
    if original_m1_index is None or repaired_m1_index is None:
        raise SystemExit(f"cannot verify corner repair without Metal1 {METAL1}")
    before = db.Region(original_corner.begin_shapes_rec(original_m1_index))
    after = db.Region(repaired_corner.begin_shapes_rec(repaired_m1_index))
    before.merge()
    after.merge()
    if not (before - after).is_empty():
        raise SystemExit("prepared GDS removed original corner Metal1")
    additions = after - before
    allowed = db.Region()
    for bridge in GF180_CORNER_M1_BRIDGES:
        allowed.insert(bridge)
        if not _region_contains(after, bridge):
            raise SystemExit(f"prepared GDS is missing Metal1 bridge {bridge}")
    if additions.is_empty():
        raise SystemExit("prepared GDS contains none of the expected Metal1 additions")
    if not (additions - allowed).is_empty():
        raise SystemExit("prepared GDS changed corner Metal1 outside bridge boxes")

    return {
        "hierarchical_via_cells_renamed": len(expected_renames),
        "hierarchical_via_cell_renames": expected_renames,
        "corner_cell": GF180_CORNER_CELL,
        "corner_metal1_bridges": [
            [box.left, box.bottom, box.right, box.top]
            for box in GF180_CORNER_M1_BRIDGES
        ],
        "corner_metal1_bridge_count": len(GF180_CORNER_M1_BRIDGES),
    }


def verify_klayout_drc_repairs(original: db.Layout, repaired: db.Layout) -> dict:
    """Verify exact bend/logo additions and prove no source mask was removed."""

    if original.dbu != repaired.dbu:
        raise SystemExit("cannot compare KLayout repairs across mismatched DBUs")
    if original.dbu != 0.001:
        raise SystemExit("KLayout repair verification requires 0.001 um dbu")

    bend_records = []
    original_m1 = original.find_layer(*METAL1)
    repaired_m1 = repaired.find_layer(*METAL1)
    for name, spec in KLAYOUT_BEND_SPECS.items():
        source_cell = original.cell(name)
        result_cell = repaired.cell(name)
        if source_cell is None:
            if result_cell is not None:
                raise SystemExit(f"prepared GDS unexpectedly added cell {name}")
            continue
        if result_cell is None or original_m1 is None or repaired_m1 is None:
            raise SystemExit(f"prepared GDS cannot verify {name} Metal1 repair")
        polygon = _find_exact_polygon(
            source_cell, original_m1, spec, f"original {name} Metal1"
        )
        before = db.Region(source_cell.shapes(original_m1))
        after = db.Region(result_cell.shapes(repaired_m1))
        before.merge()
        after.merge()
        cover = _outward_manhattan_cover(db.Region(polygon))
        expected_additions = cover - before
        if not (before - after).is_empty():
            raise SystemExit(f"prepared GDS removed original {name} Metal1")
        if not _same_region(after - before, expected_additions):
            raise SystemExit(f"prepared GDS changed {name} outside its overlay")
        if after.count() != 1:
            raise SystemExit(f"prepared GDS split the {name} Metal1 conductor")
        pieces = _bounded_overlay_pieces(cover)
        bend_records.append(
            {
                "cell": name,
                "source_polygon_bbox": [
                    polygon.bbox().left,
                    polygon.bbox().bottom,
                    polygon.bbox().right,
                    polygon.bbox().top,
                ],
                "source_polygon_area_dbu2": polygon.area(),
                "added_area_dbu2": expected_additions.area(),
                "overlay_polygon_count": len(pieces),
                "overlay_max_points": max(
                    piece.num_points_hull() for piece in pieces
                ),
            }
        )

    source_logo = original.cell(GDSFACTORY_LOGO_CELL)
    result_logo = repaired.cell(GDSFACTORY_LOGO_CELL)
    logo_patches = []
    if source_logo is None:
        if result_logo is not None:
            raise SystemExit(
                f"prepared GDS unexpectedly added cell {GDSFACTORY_LOGO_CELL}"
            )
    else:
        if result_logo is None:
            raise SystemExit(f"prepared GDS dropped cell {GDSFACTORY_LOGO_CELL}")
        if source_logo.bbox() != GDSFACTORY_LOGO_BBOX:
            raise SystemExit(f"unexpected original logo bbox {source_logo.bbox()}")
        original_m5 = original.find_layer(*METAL5)
        repaired_m5 = repaired.find_layer(*METAL5)
        if original_m5 is None or repaired_m5 is None:
            raise SystemExit("prepared GDS cannot verify the Metal5 logo repair")
        _find_exact_polygon(
            source_logo,
            original_m5,
            GDSFACTORY_LOGO_TARGET,
            f"original {GDSFACTORY_LOGO_CELL} Metal5 target",
        )
        before = db.Region(source_logo.shapes(original_m5))
        after = db.Region(result_logo.shapes(repaired_m5))
        before.merge()
        after.merge()
        expected_additions = _logo_patch_region() - before
        if not (before - after).is_empty():
            raise SystemExit("prepared GDS removed original logo Metal5")
        if not _same_region(after - before, expected_additions):
            raise SystemExit("prepared GDS changed logo Metal5 outside its patches")
        if after.count() != before.count():
            raise SystemExit("prepared GDS connected separate logo Metal5 shapes")
        logo_patches = [
            [[x, y] for x, y in coordinates]
            for coordinates in GDSFACTORY_LOGO_M5_PATCHES
        ]

    return {
        "manhattan_grid_um": KLAYOUT_MANHATTAN_GRID * original.dbu,
        "bend_overlays": bend_records,
        "bend_overlay_count": len(bend_records),
        "logo_cell": GDSFACTORY_LOGO_CELL if source_logo is not None else None,
        "logo_metal5_patches": logo_patches,
        "logo_metal5_patch_count": len(logo_patches),
    }


def prepare(args: argparse.Namespace) -> None:
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    layout = load(source)
    top = sole_top(layout)
    if layout.dbu != 0.001:
        raise SystemExit(f"source dbu must be 0.001 um, got {layout.dbu}")
    magic_repairs = apply_magic_drc_repairs(layout)
    klayout_repairs = apply_klayout_drc_repairs(layout)
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
        f"source bbox={box}; centered by ({dx}, {dy}) um; "
        f"Magic repairs={magic_repairs['corner_metal1_bridge_count']} Metal1 "
        f"bridges, {magic_repairs['hierarchical_via_cells_renamed']} "
        f"hierarchy-safe via cells; KLayout repairs="
        f"{klayout_repairs['bend_overlay_count']} bend overlays, "
        f"{klayout_repairs['logo_metal5_patch_count']} logo patches"
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
    verified_magic_repairs = verify_magic_drc_repairs(original_layout, source)
    verified_klayout_repairs = verify_klayout_drc_repairs(original_layout, source)
    centered_box = bbox_um(source_top, source.dbu)
    original_box = bbox_um(original_top, original_layout.dbu)
    repair_record = {
        "hierarchical_via_cells_renamed": verified_magic_repairs[
            "hierarchical_via_cells_renamed"
        ],
        "corner_cell": verified_magic_repairs["corner_cell"],
        "corner_metal1_bridges": verified_magic_repairs[
            "corner_metal1_bridges"
        ],
        "corner_metal1_bridge_count": verified_magic_repairs[
            "corner_metal1_bridge_count"
        ],
        "reason": (
            "preserve legal foundry via generators across Magic GDS import and "
            "close three same-net M1.2b corner-rail notches"
        ),
    }

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
        "magic_drc_repairs": repair_record,
        "klayout_drc_repairs": {
            **verified_klayout_repairs,
            "reason": (
                "cover the original smooth Metal1 bends on the GF180 5 nm "
                "Manhattan grid and close two same-polygon Metal5 wide-rule "
                "staircase transitions"
            ),
        },
        "padring_source": "external GDS only; no gf180characterization padring flow used",
        "wafer_space_pdk_commit": args.pdk_commit,
    }
    manifest.write_text(json.dumps(record, indent=2) + "\n")
    print(f"final sealed GDS: {output} sha256={record['artifact_sha256']}")


def verify(args: argparse.Namespace) -> None:
    """Verify a committed sealed artifact without its external source GDS."""

    artifact = Path(args.input).resolve()
    manifest_path = Path(args.manifest).resolve()
    if not artifact.is_file():
        raise SystemExit(f"final GDS does not exist: {artifact}")
    if not manifest_path.is_file():
        raise SystemExit(f"final manifest does not exist: {manifest_path}")
    with artifact.open("rb") as stream:
        header = stream.read(4)
    if header[:2] == b"\x1f\x8b":
        raise SystemExit(f"final GDS must remain uncompressed: {artifact}")
    if header != b"\x00\x06\x00\x02":
        raise SystemExit(
            f"final GDS has an invalid HEADER record (or is an LFS pointer): "
            f"{artifact}"
        )

    record = json.loads(manifest_path.read_text())
    artifact_relative = os.path.relpath(artifact)
    if record.get("artifact") != artifact_relative:
        raise SystemExit(
            f"manifest artifact is {record.get('artifact')}, expected "
            f"{artifact_relative}"
        )
    artifact_sha256 = sha256(artifact)
    artifact_md5 = md5(artifact)
    if record.get("artifact_sha256") != artifact_sha256:
        raise SystemExit("final GDS SHA-256 does not match the manifest")
    if record.get("sealed_uncompressed_sha256") != artifact_sha256:
        raise SystemExit("final GDS does not match the sealed artifact hash")
    if record.get("artifact_md5") != artifact_md5:
        raise SystemExit("final GDS MD5 does not match the manifest")

    checksum_relative = record.get("md5_file")
    checksum_path = Path(checksum_relative).resolve() if checksum_relative else None
    if checksum_path is None or not checksum_path.is_file():
        raise SystemExit(f"manifest MD5 file does not exist: {checksum_relative}")
    expected_checksum = f"{artifact_md5}  {artifact_relative}\n"
    if checksum_path.read_text() != expected_checksum:
        raise SystemExit(f"invalid final GDS checksum file: {checksum_path}")

    layout = load(artifact)
    top = sole_top(layout)
    if top.name != args.top:
        raise SystemExit(f"final GDS top is {top.name}, expected {args.top}")
    if layout.dbu != 0.001:
        raise SystemExit(f"final GDS dbu must be 0.001 um, got {layout.dbu}")
    expected_slot = SLOTS[args.slot]
    box = bbox_um(top, layout.dbu)
    expected_box = (0.0, 0.0, expected_slot[0], expected_slot[1])
    if box != expected_box:
        raise SystemExit(f"final GDS bbox {box} does not equal {expected_box}")
    marker_index = layout.find_layer(*GUARD_RING_MK)
    if marker_index is None or db.Region(
        top.begin_shapes_rec(marker_index)
    ).is_empty():
        raise SystemExit("final GDS has no GUARD_RING_MK 167/5 geometry")
    if record.get("top") != args.top or record.get("slot") != args.slot:
        raise SystemExit("manifest top or slot does not match the final GDS")
    if tuple(record.get("bbox_um", ())) != box:
        raise SystemExit("manifest bbox does not match the final GDS")
    if record.get("guard_ring_marker") != list(GUARD_RING_MK):
        raise SystemExit("manifest seal-ring marker does not match the final GDS")
    if record.get("source_geometry_preserved") is not True:
        raise SystemExit("manifest does not prove source-geometry preservation")
    if record.get("padring_source") != (
        "external GDS only; no gf180characterization padring flow used"
    ):
        raise SystemExit("manifest does not exclude the repository padring flow")

    print(
        f"verified final GDS: {artifact_relative}; top={top.name}; "
        f"bbox={box}; sha256={artifact_sha256}; md5={artifact_md5}"
    )


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
    p = commands.add_parser("verify")
    p.add_argument("--input", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--top", required=True)
    p.add_argument("--slot", choices=SLOTS, required=True)
    p.set_defaults(func=verify)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
