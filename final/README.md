# Final external-GDS deliverable

This directory is produced by `make final-gds` and `make signoff-final`.

The flow uses `../gds/padring_test_structures.gds` as the complete incoming
layout. It does **not** generate, import, or merge the padring defined by this
repository. The incoming layout is centered in the slot, then the only geometry
merged around it is the Wafer.Space GF180MCU seal ring from the pinned PDK. The
current source also receives three fail-closed, same-net Metal1 notch fills in
its GF180 foundry corner master; `manifest.json` records those DRC repairs and
the hierarchy-only upper-via cell renames. No repository padring is added.

Run:

```sh
nix develop
make final-gds
make signoff-final
```

Override `FINAL_GDS_SOURCE`, `FINAL_GDS_TOP`, or `FINAL_GDS_SLOT` when needed.
`manifest.json` records hashes and verifies that all incoming geometry remains
present in the sealed output. `chip_top.gds.md5` is regenerated with the GDS
and can be checked with `md5sum -c final/chip_top.gds.md5`.
Raw precheck runs remain under the ignored `.signoff/precheck-run/` directory;
the reviewed evidence from the latest authoritative run is committed under
`signoff/`.

The latest manufacturing-precheck evidence is under `signoff/`. Its README is
authoritative: Magic DRC, antenna, and zero-area checks are clean, while two
density rules remain and the full KLayout DRC stage was not rerun in the latest
Magic-focused pass. The layout must not yet be treated as fully signed off.
