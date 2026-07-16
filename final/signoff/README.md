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
  --run-tag MAGIC_FIX_2026-07-16 --to Checker.MagicDRC
```

It used only Nix-store tools and the pinned dependencies below this repository's
ignored `.signoff/` directory. Exact versions and store paths are recorded in
`toolchain.txt`. The command returned exit status 1 only because the flow
reported the two pre-existing density errors after `Checker.MagicDRC` passed.

## Verdict

**Magic DRC passes with 0 errors. Overall precheck remains incomplete because
two density rules fail and this targeted rerun stopped before full KLayout
DRC.** No Magic violations were waived.

Current-artifact results executed in this run:

- one top-level cell named `chip_top`;
- origin `(0, 0)`, DBU `0.001 µm`, and exact `1x0p5` dimensions of
  `3932 × 2531 µm`;
- zero zero-area polygons;
- antenna: 0 violations;
- Magic 8.3.660 `drc(full)`: 0 violations;
- density: 2 violations — Poly2 `9.841374%` versus `≥14%` (`PL.8`) and
  Metal1 `26.505625%` versus `>30%` (`M1.4`).

The main KLayout DRC and WriteLayout stages were intentionally skipped by the
`--to Checker.MagicDRC` boundary. The retained `drc.klayout.*`,
`klayout-drc.*`, and `write-layout.command.txt` files are from the prior
2026-07-15 run and are not sign-off evidence for this repaired artifact.

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
`6cf77628966360504b24e8b2424784fed049df08e7d65e502d5c57e4c3f944be`, MD5
`4f233de57826c45bb0800aadf7c3d000`, and source SHA-256
`80df6cfa0137b981c988d9ea09a01d3969b7e14cd1207c4ae21dd485064cb7e7`.
It contains the centered external layout plus the pinned Wafer.Space seal ring;
the `gf180characterization` padring target was not used. See
`input-equivalence.txt` for the timestamp-normalized proof tying the committed
GDS to the exact layout read by this precheck run.

`metrics.json`, `flow.log`, `resolved.json`, and the individual current-stage
logs preserve the machine-readable result. The outer console transcript is
`nix-signoff.log`, and the corresponding `*.command.txt` files preserve the
exact subprocess commands.
