# GF180 final-GDS precheck results

Run date: 2026-07-16 UTC

Input: `final/chip_top.gds`, top cell `chip_top`, Wafer.Space slot `1x0p5`.
The run used Wafer.Space precheck commit
`59207bbebaf2f5e5bb5f3e9441199a71948b1fdc`, Wafer.Space PDK commit
`ac7d8696de96a4d708e768b607ae37f02207a354`, and LibreLane commit
`f18a07aabb2dd3d6a7e3acc8c3b3621baa784a08` from this repository's
`flake.lock`.

The authoritative Magic verification was the pinned precheck flow through its
checker stage:

```sh
nix develop --accept-flake-config --no-write-lock-file --command \
  env PDK_ROOT="$PWD/.signoff/pdk" PDK=gf180mcuD \
  python3 .signoff/precheck/precheck.py \
  --input final/chip_top.gds --top chip_top --slot 1x0p5 \
  --workers max --threads 1 --dir .signoff/precheck-run \
  --run-tag KLAYOUT_FIX_2026-07-16 --to Checker.MagicDRC
```

The authoritative KLayout main DRC then ran on that flow's exact generated-ID
layout:

```sh
nix develop --accept-flake-config --no-write-lock-file --command \
  make klayout-drc-final \
  KLAYOUT_DRC_INPUT=.signoff/precheck-run/runs/KLAYOUT_FIX_2026-07-16/04-klayout-generateid/chip_top.gds \
  KLAYOUT_DRC_RUN_TAG=KLAYOUT_DRC_FIX_2026-07-16
```

Both commands used only Nix-store tools and the pinned dependencies below this
repository's ignored `.signoff/` directory. Exact versions and store paths are
recorded in `toolchain.txt`. The precheck command reached and passed the Magic
checker, then returned 1 solely because the two density findings were deferred.
The authoritative KLayout command returned 0.

## Verdict

**Magic DRC and complete KLayout main DRC both pass with 0 errors. Two density
rules remain intentionally deferred.** The artifact is not fully signed off
until density is resolved; no DRC violation was waived.

Current-artifact results executed in this run:

- one top-level cell named `chip_top`;
- origin `(0, 0)`, DBU `0.001 µm`, and exact `1x0p5` dimensions of
  `3932 × 2531 µm`;
- zero zero-area polygons;
- antenna: 0 violations;
- Magic 8.3.660 `drc(full)`: 0 violations;
- KLayout 0.30.9 main DRC: 0 markers across 649 rule categories;
- density: 2 violations — Poly2 `9.841374%` versus `≥14%` (`PL.8`) and
  Metal1 `26.505627%` versus `>30%` (`M1.4`), intentionally deferred.

## KLayout correction and repair

The old KLayout zero was invalid. The generic precheck adapter passed
`decks=all,-antenna,-density,-cup`, `variant=gf180mcuD`, `workers=max`, and
`threads=1` to a raw foundry deck that expects native switches such as `feol`,
`beol`, `offgrid`, `metal_top`, `metal_level`, and `mim_option`. Its log showed
FEOL, BEOL, and off-grid all disabled, so only 15 MIM/dummy categories ran.

The replacement is fail-closed and uses the exact raw deck from pinned PDK
commit `ac7d8696de96a4d708e768b607ae37f02207a354`. It removes the CUP include,
selects variant D (`11K`, `5LM`, MIM-B), uses the PDK macro's documented deep
mode, enables FEOL/BEOL/off-grid, disables connectivity, and runs one Nix-store
KLayout thread. Antenna and density remain their separate precheck stages. The
input SHA-256 is
`a1fc8aa09d9703b633faf50682a2a1122c72a489502d0ebae7e917c9f635b305`, and the
pinned source-deck SHA-256 is
`c613376efb0eb6a250073247225cc5d5d6935b73d10f85a8d1a8d221b6090568`.

The previous complete run's 594 markers were:

- `metal1_angle`: 300;
- `metal1_OFFGRID`: 286;
- `M1.1`: 6;
- `MT.2b`: 2.

The final-GDS builder now identifies the exact smooth Metal1 polygon in each of
`ts_bend` and `ts_bend_s` by cell, bbox, area, point count, and direct-shape
count. It inserts the smallest outward horizontal-strip cover on the GF180
5 nm grid, preserves every original Metal1 point, proves the conductor remains
one component, and bounds each output polygon to 180 points. The two covers add
only `0.086650 µm²` and `0.060974 µm²`, respectively, and clear all 592 Metal1
angle, grid, and minimum-width markers.

The two `MT.2b` markers came from staircase transitions on one Metal5 polygon
in `gdsfactory_logo`. Two 45-degree triangles of `1.125 µm²` each close those
transitions. The builder proves that they do not overlap prior Metal5 or join
separate components. `final/manifest.json` records every addition, and the
finish phase independently proves that no original mask geometry was removed
and that no other Metal1 or Metal5 geometry was added in the repaired cells.

The completed deep run took `949.716708 s`, evaluated all 649 emitted rule
categories, and reports 0 markers. The JSON and marker database are both
committed below.

The supplied 2,409-marker vendor figure was not reproduced on the current GDS.
A flat-mode diagnostic spent one hour expanding 4,743,368 contacts and did not
finish rule `CO.6`; it is not presented as sign-off evidence. The completed
deep run is the repository default and its count is the only complete
current-artifact result.

## Magic repair

The former 271 Magic markers consisted of 90 Via3 and 175 Via4 importer
artifacts plus 6 Metal1 spacing markers. The precheck's broad `*_CDNS_*`
flatglob was flattening legal foundry M4/M3 and M5/M4 via generators into
narrow Magic tiles. The build now renames 302 cells in those two helper
families to preserve their hierarchy; their mask geometry is unchanged.

The six M1.2b markers were two instances of three 0.28 µm notches in the
same already-connected foundry corner power rail. The build fills those three
notches only after proving both bridge sides belong to one merged Metal1
polygon. It also checks the expected corner-cell bbox and bounds every Metal1
addition to the three recorded boxes. `final/manifest.json` records the repair
count and coordinates.

The pinned wrapper report is `magic-drc.rpt`, and `magic-drc.lyrdb` contains no
categories or items. `magic-drc.log` ends with `No errors found` and
`[INFO] COUNT: 0`. Magic still emits 233 foundry-cell duplicate/self-placement
warnings during GDS import; those warnings are preserved in the log and are
not counted as DRC markers.

The final artifact has SHA-256
`53b33f39fad23fa581bc7a9fd5e4adc875a57fa6ad75d29084dbf9b3e74b1bf9`, MD5
`1c5109d6a668de69250925b70ce00889`, and source SHA-256
`80df6cfa0137b981c988d9ea09a01d3969b7e14cd1207c4ae21dd485064cb7e7`.
It contains the centered external layout plus the pinned Wafer.Space seal ring;
the `gf180characterization` padring target was not used. See
`input-equivalence.txt` for the timestamp-normalized proof tying the committed
GDS to the exact layout read by this precheck run.

`metrics.json` and `drc.klayout.json` preserve the combined machine-readable
result. `flow.log` and `resolved.json` describe the pinned precheck stages
through Magic; they do not supersede the authoritative KLayout JSON. The
`nix-signoff.log` file is the Magic flow console transcript, while
`klayout-nix-signoff.log` is the corrected KLayout transcript. The
corresponding `*.command.txt` files preserve the exact subprocess commands,
and `drc.klayout.lyrdb` is loadable in KLayout's marker browser.
