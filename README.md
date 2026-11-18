# Geometry pipeline (figurine lighter sleeve + display stand)

Reproducible, script-only pipeline. All lengths in mm. Parameters live in `config.json`;
most of them can also be overridden on the command line.

## Setup (once)

```bash
cd "<project>"                      # folder that contains lighter-*.3mf
/c/Python314/python -m venv pipeline/.venv
pipeline/.venv/Scripts/python -m pip install numpy scipy trimesh manifold3d shapely matplotlib pillow fast_simplification
# unzip the source 3MF to work/3mf/ (3D/3dmodel.model, Metadata/*.config, _rels, [Content_Types].xml)
```

Blender 5.1 is used headless only for diagnostic renders and the BVH self-intersection check
(path in `common.py`, override with env `BLENDER_EXE`).

## Run

```bash
cd pipeline/geometry
export PYTHONIOENCODING=utf-8
../.venv/Scripts/python run_all.py            # = the four steps below, in order (~5-8 min)

../.venv/Scripts/python analyze_case.py       # Task 1 -> output/report/case_metrics.json + kaynak_*.png
../.venv/Scripts/python build_case_v2.py      # Task 2 -> output/print/panter_kilif_v2.{3mf,stl},
                                              #           work/preview/case_v2_lowpoly.stl,
                                              #           output/report/case_v2_validation.json + v2_*.png
../.venv/Scripts/python build_stand.py        # Task 3 -> output/print/stand/*.stl, stand_tumu.3mf,
                                              #           output/print/stand_montajli.stl,
                                              #           output/preview/stand_dolu_montaj.glb,
                                              #           output/report/stand_params.json, stand_layout.json
../.venv/Scripts/python make_report.py        # Task 4 -> output/report/RAPOR.md (from the JSON files)
```

### Design Pack (recommended for new figures)

Instead of editing `config.json` manually, create a Design Pack JSON in `design_pack/` and run:

```bash
../.venv/Scripts/python run_all.py --design-pack design_pack/your_figure_v1.json
```

This loads the design pack, validates it against `design_pack_schema.json`, writes a merged `config.json` and `render_args.json`, then runs the full pipeline. See `design_pack/template.json` for a blank template and `design_pack/panter_v1.json` for a complete example.

The Design Pack contains:
- `figure_id`, `source` (meshy/higgsfield/manual/bambu_studio)
- `assets.model_3mf` — path to source 3MF (unzipped to `work/3mf/`)
- `geometry_overrides` — any `config.json` keys under `lighter`, `case`, `stand`
- `render_overrides` — arguments for `turntable.py` (start_phi, lens, samples, etc.)
- `marketing` — hero angles, lifestyle prompts, social crops, AR/QR config, branding

### Overrides

| script | flag | meaning (default from config.json) |
|---|---|---|
| build_case_v2.py | `--z-cut auto\|<mm>` | cut plane in source coordinates (`auto` = knee of the area-vs-z curve, rounded up to a 0.12 mm layer) |
| | `--plinth-height <mm>` | plinth height (3.0) |
| | `--hole-d <mm>` | modelled pin-hole diameter (3.3) |
| | `--hole-chamfer <mm>` | 45° chamfer at the hole mouth (0.4) |
| | `--hole-mode auto\|through\|blind` | auto: through if floor ≤ 4 mm, else blind 3.2 mm |
| | `--name <basename>` | output file names (panter_kilif_v2) |
| | `--skip-selfint` / `--no-render` | skip the Blender steps |
| build_stand.py | `--pins 8,4,2` | pins per tier, bottom → top |
| | `--pitch <mm>` | vertical pitch of the plate top surfaces (80) |
| all | `--config <file>` | alternative config file |

Other knobs (config.json → `case` / `stand`): growth-rate threshold for auto z_cut, plinth outset (0.02),
plinth colour rule, pin Ø/height/chamfer, min case gap (4), plate thickness (4), margins,
column Ø (16), hex AF (10) and joint clearance (0.2/side), spigot length, sign size/tilt/height.

## New figure

**Option A — Design Pack (recommended):**
1. Copy `design_pack/template.json` to `design_pack/your_figure_v1.json`
2. Edit: set `figure_id`, `source`, `assets.model_3mf`, and any overrides
3. Unzip the new 3MF to `work/3mf/` (or place at the path in `assets.model_3mf`)
4. Delete `work/cache/`
5. `../.venv/Scripts/python run_all.py --design-pack design_pack/your_figure_v1.json`
6. Check `case_metrics.json` (cavity axis/size, wall tops, z_cut knee) and the PNGs before printing.

**Option B — Manual config:**
1. Unzip the new 3MF to `work/3mf/` (or point `source_model` / `source_metadata_dir` in a copied config).
2. Delete `work/cache/` (the parsed-mesh cache is keyed on file mtime, but stale derived caches can remain).
3. `run_all.py`. Check `case_metrics.json` (cavity axis/size, wall tops, z_cut knee) and the PNGs before printing.
   The cavity is detected as the largest hole (>100 mm²) in the horizontal sections; the pin hole is placed on its centroid.

## Method notes

- Parser: regex over 16 MB chunks of the model XML (no DOM); per-triangle `pid/p1` and Bambu `paint_color`
  are both read and written (they are kept identical).
- CSG: manifold3d (float64 `Mesh64`). v2 = (source ∪ plinth prism) − pin hole. The plinth prism (top exactly at
  z_cut) overlaps the 0…z_cut slab of the source, so the union both files that slab off and fuses the plinth;
  its outline is the filled section at z_cut offset by 0.02 mm (avoids zero-width knife-edge contacts).
  Triangle provenance comes from manifold `face_id` (source ids 0…n-1, plinth 1e7+, hole 2e7+), which is how
  per-triangle colours survive the boolean.
- Self-intersection check: Blender `BVHTree.overlap` (same as the 3D-Print Toolbox), pairs sharing a vertex ignored.
- Stand: exact CSG primitives; ring radii are the smallest (0.5 mm steps) giving ≥ min gap between the
  *top-view silhouettes* of neighbouring cases (whole figure, not only the footprint).
