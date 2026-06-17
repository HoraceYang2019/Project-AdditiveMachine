# Pipeline

## Folder Structure

- `Data`
  - Raw and generated working data such as `csv`, `json`, `G-code`, `output`, uploaded inputs, and exported MPF files.
- `DataPreprocess`
  - MPF parsing, schema generation, examples, schemas, and preprocessing notebooks/scripts.
- `LPBFOntology`
  - `Knowledge`
    - AMH-350 knowledge graph, Protégé tree view, and semantic graph files.
  - `Models`
    - Reusable ontology models such as hardware, dataflow, and embodied-AI loop definitions.
  - `Docs`
    - Ontology-related design notes and module specifications.
- `UserInterfaceDesign`
  - Dashboard HTML templates, CSS, JavaScript, and UI reference artifacts.
- `WebServices`
  - The local dashboard web service entry point and API layer.

## Runtime Flow

1. `DataPreprocess/parse_mpf_to_json.py` parses MPF into structured output under `Data/output`.
2. `WebServices/final_dashboard.py` loads parsed output plus uploaded thermal / Edge data.
3. `UserInterfaceDesign` assets render the dashboard and playback views.
4. `LPBFOntology/Knowledge` and `LPBFOntology/Models` provide the ontology and rule references for identification / inference design.
