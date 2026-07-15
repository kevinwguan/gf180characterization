# GF180 final-GDS precheck results

Run date: 2026-07-15 UTC

Input: `final/chip_top.gds`, top cell `chip_top`, Wafer.Space slot `1x0p5`.
The run used Wafer.Space precheck commit
`59207bbebaf2f5e5bb5f3e9441199a71948b1fdc`, Wafer.Space PDK commit
`ac7d8696de96a4d708e768b607ae37f02207a354`, and LibreLane commit
`f18a07aabb2dd3d6a7e3acc8c3b3621baa784a08` from this repository's
`flake.lock`.

The authoritative command was:

```sh
nix develop --accept-flake-config --command make signoff-final
```

It used only Nix-store tools and the pinned dependencies cloned below this
repository's ignored `.signoff/` directory. The raw run tag is
`RUN_2026-07-15_17-53-26`; all 16 stages executed and WriteLayout completed
before the command returned exit status 2 for the two deferred density errors.
Exact versions and store paths are recorded in `toolchain.txt`.

## Verdict

**FAIL overall — antenna and KLayout DRC pass, but density and Magic DRC
fail.** No violations were waived.

Passing checks:

- one top-level cell named `chip_top`;
- origin `(0, 0)`, DBU `0.001 µm`, and seal-ring marker `167/5` present;
- exact standard `1x0p5` dimensions, `3932 × 2531 µm`;
- zero zero-area polygons;
- antenna: zero violations in every pinned rule bucket;
- KLayout DRC: zero violations in every pinned rule bucket.

Failing checks:

- density: 2 rules — Poly2 `9.841374%` versus `≥14%` (`PL.8`), and
  Metal1 `26.505615%` versus `>30%` (`M1.4`);
- Magic `drc(full)`: 271 top-level error boxes — 90 Via3-width
  (`V3.1 + 2 * V3.4`), 6 Metal1-spacing (`M1.2b`), and 175 Via4-width
  (`V4.1 + 2 * V4.4`).

The current pinned precheck wrapper completed under Magic 8.3.660. Its report
and marker database are preserved as `magic-drc.rpt` and `magic-drc.lyrdb`.
There was no direct-Magic fallback. The superseded host-Magic summary and
wrapper-error files were removed from the canonical evidence set.
Magic also logged 233 duplicate/self-placement warning lines while importing
cells and ignored the extra self-placed instances. Those warnings are preserved
in `magic-drc.log`, are not included in the 271-marker count, and are another
reason this result must not be treated as complete sign-off.

The committed final artifact has SHA-256
`3c2da6d44d631fdf6156987dbd6fedfb299b1746c29ae18d6b0d27cdf8a6435f`, MD5
`da3a2fd7038bb649f482e29861a79aa1`, and source SHA-256
`80df6cfa0137b981c988d9ea09a01d3969b7e14cd1207c4ae21dd485064cb7e7`.
It contains only that centered external layout plus the pinned Wafer.Space seal
ring; the `gf180characterization` padring target was not used. See
`input-equivalence.txt` for the timestamp-normalized proof tying the final GDS
to the precheck input geometry.

The `.lyrdb` files can be opened in KLayout's Marker Database browser to inspect
each violation geometrically. `metrics.json`, `flow.log`, `resolved.json`, and
the individual tool logs preserve the machine-readable result. The outer
console transcript is `nix-signoff.log`, and the `*.command.txt` files preserve
the exact subprocess commands from the principal stages.
