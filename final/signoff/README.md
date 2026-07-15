# GF180 final-GDS precheck results

Run date: 2026-07-15 UTC

Input: `final/chip_top.gds`, top cell `chip_top`, Wafer.Space slot `1x0p5`.
The run used Wafer.Space precheck commit
`59207bbebaf2f5e5bb5f3e9441199a71948b1fdc`, Wafer.Space PDK commit
`ac7d8696de96a4d708e768b607ae37f02207a354`, and LibreLane commit
`5fe3db1bbea68aa9973a9e7b045d24af1a089571`.

## Verdict

**FAIL — the layout is not signed off.** No violations were waived.

Passing checks:

- one top-level cell named `chip_top`;
- origin `(0, 0)`, DBU `0.001 µm`, and seal-ring marker `167/5` present;
- exact standard `1x0p5` dimensions, `3932 × 2531 µm`;
- zero zero-area polygons.

Failing checks:

- density: 2 rules — Poly2 `9.841365%` versus `≥14%` (`PL.8`), and
  Metal1 `26.499893%` versus `>30%` (`M1.4`);
- antenna: 139 violations across the rule counts in `antenna.klayout.json`;
- KLayout DRC: 1,872 violations, all `MIMTM.9` (minimum Via4 spacing of
  `0.5 µm` for a sea of vias on a MIM top plate);
- Magic `drc(full)`: 928 top-level error boxes in the `DF.3a` and `M1.2b`
  rule families.

The pinned LibreLane Magic wrapper expects a newer Magic Tcl command (`units`)
than host Magic 8.3.530 provides. The wrapper failure is preserved in
`magic-wrapper-error.log`. To avoid losing the Magic check, the same generated
precheck GDS was run directly with the stock GF180 `drc(full)` style; its result
is recorded in `magic-summary.json`. Magic also warned that marker layer
`153/51` is unknown to its importer; KLayout did read and check that layer.

The `.lyrdb` files can be opened in KLayout's Marker Database browser to inspect
each violation geometrically.
