# DED Hardware-First Ontology

## Folder Layout

- [`Knowledge/`](./Knowledge)
  - Knowledge graph, Protégé presentation tree, and semantic graph files used for dashboard-facing reasoning.
- [`Models/`](./Models)
  - Reusable ontology models such as hardware, dataflow, and embodied-AI loop definitions.
- [`Docs/`](./Docs)
  - Supporting design documents and module specifications.

Use [`amh350-protege-tree.ttl`](./Knowledge/amh350-protege-tree.ttl) for a simple
presentation in the Protégé `Classes` tab. It shows only one direct child below
`owl:Thing`: `機台：AMH-350`.

Use [`amh350-dataflow-ontology.ttl`](./Models/amh350-dataflow-ontology.ttl) when you
want to inspect formal data-flow relationships in `OntoGraf`. Use
[`ded-hardware-ontology.ttl`](./Models/ded-hardware-ontology.ttl) when you need the
broader reusable domain model.

Use [`amh350-semantic-graph.ttl`](./Knowledge/amh350-semantic-graph.ttl) for the formal
AMH-350 semantic graph patterned after the nearby CNC and MachineCenter
ontology examples. It is the recommended file for future inference, SPARQL
queries, and dashboard integration.

Use [`amh350-knowledge.ttl`](./Knowledge/amh350-knowledge.ttl) when you want to open the
Knowledge model separately. It contains the time-alignment knowledge and the
`G_High` quality threshold rules, plus the inference rule table for
recommendation targets such as laser power, feed rate, powder supply, spot
diameter, and dwell time.

Use [`amh350-embodied-ai-loop.ttl`](./Models/amh350-embodied-ai-loop.ttl) when you
want a separate model for the whiteboard-style embodied-AI loop:
`Sensing -> Identification -> Inference -> Evaluation -> Adaptation`.
It is designed to stay independent from the presentation tree while still
mapping cleanly to dashboard payload keys such as `state`, `cause`,
`recommended_action`, and `recommended_parameter_change`.

## Formal AMH-350 Semantic Graph

Open `Knowledge/amh350-semantic-graph.ttl` and inspect its individuals with Protégé
`Individuals by class`, `Object property assertions`, or `OntoGraf`. The graph
separates taxonomy from runtime relationships:

```text
AMH-350
├── thermal camera
│   └── Time + G_High signal
├── Edge device
│   └── sample_ms + XYZ + g_high + align_error_ms signals
└── MPF / G-code
    ↓
multi-sensor synchronization window
    ↓
NC block + toolpath segment alignment
    ↓
quality threshold rules
    ↓
dashboard diagnosis display
```

The presentation tree and semantic graph intentionally serve different
purposes. `Knowledge/amh350-protege-tree.ttl` is easier to expand during a report;
`Knowledge/amh350-semantic-graph.ttl` uses object properties so the data flow remains
semantically correct. `Knowledge/amh350-knowledge.ttl` is kept separate for the Knowledge
rules so it does not appear inside the presentation tree.

## Model Direction

```text
AMH-350 machine
├── SINUMERIK controller
├── laser source
├── powder feeder
├── thermal camera
└── Edge gateway
    ↓
manufacturing run
├── MPF / NC program
├── layers and toolpath segments
├── thermal dataset
├── Edge dataset
├── sensor alignment result
└── quality assessment
```

## Open In Protégé

1. Open Protégé.
2. Select `File > Open`.
3. Open `LPBFOntology/Knowledge/amh350-protege-tree.ttl`.
4. Open the `Classes` tab.
5. Expand `owl:Thing`.
6. Expand `機台：AMH-350`.

The four branches describe the thermal camera, Edge device, MPF program, and
combined processing flow. Open `Knowledge/amh350-knowledge.ttl` separately if you want to
show the Knowledge rules.

Each source branch separates:

- `收到資訊` or `讀取資訊`: the individual fields collected from the source.
- `產生資料`: the CSV, JSON, or parsed toolpath dataset.
- `資料流向`: the path from the source dataset to automatic alignment.
- `用途`: why the data is needed by the dashboard.

To view the model as a graph:

1. Select `Window > Tabs > OntoGraf`.
2. Search for `機台：AMH-350`.
3. Double-click the machine node to expand its components and manufacturing run.
4. Continue expanding the sensor and MPF nodes to inspect the collected signals,
   datasets, alignment step, quality judgment, and dashboard display.

The `Classes` tab is a taxonomy view and will always start from `owl:Thing`.
Protégé cannot remove that OWL root node. The presentation tree keeps the root
clean by placing only `機台：AMH-350` directly below it.

## Main Classes

| Layer | Classes |
| --- | --- |
| Hardware | `ManufacturingMachine`, `Controller`, `LaserSource`, `PowderFeeder`, `ThermalCamera`, `EdgeGateway` |
| Program and process | `NCProgram`, `ManufacturingRun`, `Layer`, `ToolpathSegment`, `ProcessParameterEvent` |
| Sensor data | `ThermalDataset`, `EdgeDataset`, `ThermalObservation`, `EdgeObservation` |
| Analysis | `SensorAlignment`, `QualityAssessment`, `AssessmentBand` |

## Example Trace

The file includes a small example mapped from the current project output:

```text
Machine_AMH_350
  supportsRun Run_20260525450715000610
    executesProgram NCProgram_20260525450715000610
    hasDataset ThermalDataset_20260525
    hasDataset EdgeDataset_20260525
    hasAlignment Alignment_20260525
    hasAssessment Assessment_20260525
```

The ontology intentionally stores only representative observations. The raw CSV
and JSON files should remain outside the ontology; the TTL file stores their
semantic relationships and selected summary values.
