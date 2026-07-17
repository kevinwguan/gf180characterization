# Final external-GDS deliverable

This directory is produced by `make final-gds` and `make signoff-final`.
It is also the directory hashed and uploaded by GitHub Actions. LibreLane's
independent implementation views are written to `../librelane/`. The existing
`make librelane-condensed` workflow step materializes this LFS object and runs
`verify-final-gds` before implementation starts.

The flow uses `../gds/padring_test_structures.gds` as the complete incoming
layout. It does **not** generate, import, or merge the padring defined by this
repository. The incoming layout is centered in the slot, then the only geometry
merged around it is the Wafer.Space GF180MCU seal ring from the pinned PDK. The
current source also receives three fail-closed, same-net Metal1 notch fills in
its GF180 foundry corner master, GF180-grid covers over two smooth Metal1 bends,
and two same-polygon Metal5 logo patches. `manifest.json` records those DRC
repairs and the hierarchy-only upper-via cell renames. No repository padring is
added.

Run:

```sh
nix develop --accept-flake-config --command make final-gds
nix develop --accept-flake-config --command make signoff-final
```

The final-GDS and sign-off targets refuse host Python, Git, Magic, or KLayout
and verify the pinned Wafer.Space dependency commits before running.

Override `FINAL_GDS_SOURCE`, `FINAL_GDS_TOP`, or `FINAL_GDS_SLOT` when needed.
`manifest.json` records hashes and verifies that all incoming geometry remains
present in the sealed output. `chip_top.gds.md5` is regenerated with the GDS
and can be checked with `md5sum -c final/gds/chip_top.gds.md5`. The `.gds`
remains uncompressed and is tracked through Git LFS.
Raw precheck runs remain under the ignored `.signoff/precheck-run/` directory;
the reviewed evidence from the latest authoritative run is committed under
`../signoff/`.

The latest manufacturing-precheck evidence is under `../signoff/`. Its README
is authoritative: Magic DRC, complete KLayout main DRC, antenna, and zero-area
checks are clean. Two density rules remain intentionally deferred, so the
layout must not yet be treated as fully signed off.
