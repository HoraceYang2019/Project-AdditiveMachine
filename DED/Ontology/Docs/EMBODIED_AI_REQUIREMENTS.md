# AMH-350 Embodied AI Requirement Draft

## Goal

This document formalizes the whiteboard loop into an implementable requirement
for the current AMH-350 DED dashboard project.

Target loop:

1. Sensing
2. Identification
3. Inference
4. Evaluation
5. Adaptation
6. Apply action and return to sensing

The loop must work on top of the current MPF + thermal + Edge integration
instead of becoming a separate standalone prototype.

## Current Implementation Status

### Already done

- The dashboard foundation is stable enough to serve as the main integration
  surface.
- MPF + thermal + Edge are already bundled as one processing package so the
  dashboard does not accidentally mix different sources after file switching.
- The first version of time alignment is already available.
- The current alignment logic is feature-based and uses:
  - Edge minimum Z point
  - laser-on feature
  - thermal rise starting point
- Heat playback, toolpath playback, and right-side information are already
  integrated into one dashboard workflow.
- MPF process parameters are already readable, including:
  - `laser_power_w`
  - `spot_diameter_mm`
  - `powder_supply_on`
  - `dwell_s`
- Ontology and rule table are already connected.
- The rule table is already shown as a separate dashboard module and already
  has ontology backing.

### Currently in progress

The project is currently building the foundation of inference, not full
automatic inference yet.

The current focus is to connect:

- which data must be read
- which rules must be used
- which parameters should be recommended after judgment
- how the same rules stay consistent across dashboard, ontology, and backend
  payloads

### Not completed yet

The system does not yet fully and automatically answer:

`what process parameter should be adjusted right now`

The missing path is still:

`aligned data -> rule evaluation -> live cause/result -> adaptation recommendation`

## System Scope

The embodied-AI workflow starts from one manufacturing machine and its
supporting data sources:

- Machine: `AMH-350`
- Program/process source: MPF / G-code
- Thermal source: thermal imager dataset
- Edge source: Edge dataset

The system is expected to combine sensor data and process data, identify
machine or process status, infer cause, evaluate impact, and generate an
adaptation recommendation.

## Stage Requirements

### 1. Sensing

Purpose:
Collect raw sensing data and process context for one manufacturing run.

Required inputs:

- MPF / G-code
- Thermal time series
- Edge time series
- Parsed toolpath / layer structure
- Process parameters extracted from MPF

Required outputs:

- Aligned thermal observations
- Aligned Edge observations
- Layer and toolpath context
- Playback-ready synchronized window

Current project mapping:

- `final_dashboard.py`
- `parse_mpf_to_json.py`
- `dashboard_static/js/alignment.js`
- `dashboard_static/js/toolpath.js`
- `dashboard_static/js/coordinate.js`

Current implementation note:

- This stage is already the strongest part of the project.
- The main next need is not raw sensing itself, but turning synchronized data
  into live interpreted status.

### 2. Identification

Purpose:
Turn synchronized sensor/process observations into interpretable machine or
process status.

Typical status examples from the whiteboard:

- Robot or motion status
- Filter blocked
- Nozzle abnormal
- Process state abnormal
- Quality warning

Required outputs:

- `identified_status[]`
- `status_source`
- `status_evidence`
- `status_confidence`

Dashboard expectation:

- Show what the system thinks is happening now
- Show the supporting evidence for the current playback point

Current implementation note:

- This stage is not complete yet.
- The dashboard can already show synchronized evidence, but it does not yet
  produce a formal `identified_status[]` output.

Implementation target files:

- `schema/identification-result.schema.json`
- `examples/identification-result.example.json`
- `IDENTIFICATION_MODULE_SPEC.md`

### 3. Inference

Purpose:
Infer the most likely cause and propose a response.

Required outputs:

- `state`
- `cause`
- `confidence`
- `recommended_action`
- `recommended_parameter_change[]`
- `related_rule`
- `related_parameter[]`

This stage must reuse the existing payload contract already present in:

- `schema/inference-result.schema.json`
- `examples/inference-result.example.json`

Expected inference examples:

- Heat accumulation
- Energy density too high
- Feed rate mismatch
- Powder supply drift
- Filter blockage
- Nozzle anomaly

Current implementation note:

- The current project is at `threshold_preview` or rule-groundwork level.
- The rule table exists, but it still behaves more like a displayed rule
  source than a fully evaluated live inference engine.

### 4. Evaluation

Purpose:
Evaluate whether the inferred state affects performance or quality, and whether
the recommended response is justified.

Evaluation dimensions from the whiteboard:

- Performance
- Quality
- Baseline comparison

Required outputs:

- `evaluation_target`
- `evaluation_result`
- `evaluation_reason`
- `baseline_reference`

Baseline sources:

- Same-parameter history
- Same-layer history
- Same-path-position history

Current implementation note:

- Baseline comparison is planned but not complete.
- This is the key bridge from a simple threshold rule into evaluation-aware
  embodied AI.

### 5. Adaptation

Purpose:
Convert inference and evaluation into a concrete response or process
adjustment.

Required outputs:

- `adaptation_plan`
- `action_type`
- `action_target`
- `action_direction`
- `action_magnitude`
- `expected_outcome`

Possible adaptation targets:

- `laser_power_w`
- `feed_rate_mm_min`
- `powder_supply_on`
- `spot_diameter_mm`
- `dwell_s`
- Maintenance action such as filter inspection or nozzle inspection

Current implementation note:

- Adaptation is the main downstream stage still waiting to be connected.
- It should become the stage that turns inference output into actionable
  process recommendations.

### 6. Apply Action

Purpose:
Present or export the final response so a human operator or downstream system
can apply it.

Required forms:

- Dashboard recommendation card
- Exportable recommendation payload
- Optional regenerated MPF without overwriting the original file

## Minimum Deliverables

To claim this whiteboard requirement is implemented in the project, the system
must support the following minimum path:

1. Upload MPF + thermal + Edge
2. Align them into one playback context
3. At one playback point, identify the current status
4. Infer a cause
5. Output a recommendation using the existing inference schema
6. Show the recommendation in the dashboard

## Current Repository Alignment

The project already has a strong base for stage 1 and part of stage 3:

- Dashboard and playback flow already exist
- MPF parameter extraction already exists
- Ontology and rule table already exist
- Inference payload schema already exists

The main missing piece is the live middle path:

`aligned evidence -> identified status -> inferred cause -> evaluated impact -> adaptation recommendation`

## Recommended Implementation Order

1. Keep upload and aligned playback stable as the common entry point
2. Turn the rule table from displayed knowledge into evaluated live logic
3. Add `Identification` output for the current playback point
4. Upgrade `threshold_preview` into full `Inference`
5. Add `Evaluation` against same-parameter, same-layer, and same-path baselines
6. Add `Adaptation` plan export and dashboard action card
7. Optionally add report generation, abnormal segment marking, and MPF rewrite

## Acceptance Criteria

The whiteboard requirement is considered complete when:

- The dashboard can explain the current playback point in plain language
- The system can state not only the thermal value, but also the current status
- The system can provide at least one cause hypothesis
- The system can provide at least one response or parameter adjustment
- The output structure is reusable in dashboard, ontology, and backend payloads
- The system can preserve the original MPF and export a new file when
  adaptation is turned into process output
