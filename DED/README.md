# Final NC Schema Package

This folder contains:

- two source `MPF` files
  - [202603237504150010.MPF](./202603237504150010.MPF): original program
  - [202603237504150010_modified.MPF](./202603237504150010_modified.MPF): version with added process-control events
- a schema package for both variants
- an automation script that converts `MPF` into JSON and JSONL artifacts

## What is included

- `schema/NC-file.schema.json`
  - File-level metadata and controller setup.
- `schema/NC-block.schema.json`
  - One parsed NC block with motion state and process flags.
- `schema/thermal-imager.schema.json`
  - A thermal-camera observation schema focused on `Time` and `G_High` traces from CSV data.
- `schema/laser-process-parameters.schema.json`
  - Laser and powder settings derived from `LASER_PARA`, `/M717`, `/M718`, `/M721`, and `/M722`.
- `schema/toolpath-segment.schema.json`
  - A front-end friendly path segment for layer playback and geometry display.
- `schema/inference-result.schema.json`
  - Standard output format for one playback-point inference result, including state, cause, confidence, related rule, and recommended parameter changes.
- `examples/*.example.json`
  - Example payloads based on the current `MPF` file.
- `parse_mpf_to_json.py`
  - Converts one or more `MPF` files into structured outputs under `output/`.
- `generate_schema_package.py`
  - Rebuilds `bundle_manifest.json` from the current schema files in `schema/`.
- `bundle_manifest.json`
  - Lists the schema package metadata and local schema files.

## Automation Usage

Recommended order:

1. Generate or update the schema package.
2. Convert `MPF` files into data that follows that schema.

Generate the schema package:

```powershell
python Final\generate_schema_package.py
```

Run the parser from the project root:

```powershell
python Final\parse_mpf_to_json.py
```

Optional schema validation:

```powershell
python Final\parse_mpf_to_json.py --validate
```

By default it processes every `*.MPF` file in `Final/` and writes results to:

- `Final/output/<file-stem>/NC-file.json`
- `Final/output/<file-stem>/summary.json`
  - Derived process summary such as layer count, nominal layer height, and observed deposition Z levels.
- `Final/output/<file-stem>/NC-blocks.jsonl`
- `Final/output/<file-stem>/laser-process-parameters.jsonl`
- `Final/output/<file-stem>/toolpath-segments.jsonl`
- `Final/output/run-manifest.json`

## Suggested data model flow

1. Parse the source file into line-level `NC-block` objects.
2. Extract laser setup events into `laser-process-parameters` objects.
3. Group continuous motion with the same process state into `toolpath-segment` objects.
4. Use `thermal-imager` as the sensor-layer schema when you want to describe heat traces from CSV-based thermal-camera data.
5. Use `NC-file` as the header metadata for dashboards, reports, and APIs, and keep derived layer metrics in `summary.json`.

## Mapping from the current MPF file

- Header metadata comes from lines `1-8`.
- Machine setup appears in lines `10-16`.
- The first laser parameter event starts at line `22`:
  - `LASER_PARA(785,,2.02,1)`
  - `/M713 ; LASER safety lock on`
  - `G4 F1.`
  - `/M721 ; Powder supply`
- Deposition starts at line `37` after `/M717 ;LASER ON`.
- Deposition pauses whenever `/M718 ;LASER OFF` appears.
- Powder control is handled by `/M721` and `/M722`.
- Transform state changes between `TRAFOOF` and `TRAORI(2)`.
- The `modified` file adds extra `/M721`, `/M722`, `/G4 F10`, and `/G4 F290` events without changing the main laser path count.
## Observed layer pattern

The deposition `Z` levels visible in this file are:

- `109.982`
- `110.182`
- `110.382`
- `110.582`
- `110.782`
- `110.982`
- `111.182`
- `111.382`
- `111.582`

This suggests a nominal layer increment of about `0.2 mm`.

## Why these schemas

These schemas separate raw source detail from manufacturing meaning:

- `NC-file`
  - Show program name, machine, offset, and summary metadata.
- `NC-block`
  - Inspect raw NC content line by line.
- `thermal-imager`
  - Represent thermal-camera observations with `Time` and `G_High` samples.
- `laser-process-parameters`
  - Show current laser and powder state.
- `toolpath-segment`
  - Draw paths, color laser-on and laser-off regions, and play back layers.
- `inference-result`
  - Keep dashboard, ontology, and future adaptation modules aligned on the same inference output contract.
