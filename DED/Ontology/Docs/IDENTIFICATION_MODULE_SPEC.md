# Identification Module Spec

## Purpose

The identification module is the next required runtime module between
aligned sensing data and full inference.

It answers:

`What is happening at the current synchronized playback point?`

This is different from inference.

- Identification = current status
- Inference = probable cause and recommended response

## Position In The Loop

```text
Sensing -> Identification -> Inference -> Evaluation -> Adaptation
```

Your project already has:

- synchronized MPF + thermal + Edge
- playback context
- G_High threshold preview
- rule table definition

The identification module should be the first runtime module that converts the
current playback point into a formal status result.

## Required Runtime Inputs

At one playback point, the module should consume:

- `g_high`
- `layer_index`
- `timestamp_ms`
- `x_mm`
- `y_mm`
- `z_mm`
- `laser_on`
- `feed_rate_mm_min`
- optional MPF parameter snapshot such as:
  - `laser_power_w`
  - `spot_diameter_mm`
  - `powder_supply_on`
  - `dwell_s`

## First Version Status Set

Do not start with too many statuses.

Version 1 should only produce:

- `normal_deposition`
- `heat_accumulation_warning`
- `abnormal_heat_or_process`
- `unknown`

## Output Contract

The module should emit the schema defined in:

- `schema/identification-result.schema.json`

Example payload:

- `examples/identification-result.example.json`

Required output fields:

- `identified_status`
- `status_label`
- `status_confidence`
- `status_source[]`
- `status_reason`
- `status_evidence`
- `time_context`

## Version 1 Decision Logic

### Rule A: normal_deposition

Use when:

- `g_high` is in the good band
- the point is inside an active deposition context
- no obvious conflicting signal exists

Expected meaning:

- the current playback point looks like stable deposition

### Rule B: heat_accumulation_warning

Use when:

- `g_high` is in the warning band
- the point is inside an active deposition context
- the point is not yet in the abnormal band

Expected meaning:

- heat input or cooling behavior may be drifting away from nominal behavior

### Rule C: abnormal_heat_or_process

Use when:

- `g_high` is in the abnormal band
- or synchronized process evidence strongly contradicts the expected path state

Expected meaning:

- the process point should be treated as abnormal and forwarded to inference

### Rule D: unknown

Use when:

- required evidence is missing
- thermal sample is not valid
- playback point is outside the usable aligned context

## Dashboard Integration

The module should drive a new identification card or feed directly into the
existing right-side recommendation flow.

The minimum dashboard display should show:

- current status
- confidence
- reason
- evidence source tags

## Backend Integration

Recommended backend function names:

- `build_default_identification_result()`
- `build_playback_identification_result(...)`

Recommended state key:

- `identification_current_result`

## Relation To Inference

Once identification is stable:

- inference should consume `identification_current_result`
- inference should stop relying only on direct threshold classification
- recommendation logic should use identified status plus rule-table mapping

## Success Criteria

The identification module is successful when:

- it updates at every playback point
- it emits a stable JSON result
- it can be displayed in the dashboard
- it provides a clean handoff into inference
