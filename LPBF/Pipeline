| Stage          | Input                                      | Output                                                             |
| -------------- | ------------------------------------------ | ------------------------------------------------------------------ |
| Sensing        | Sensor signals, process parameters, images | Runtime observations and derived features                          |
| Identification | Runtime observations                       | Process states, melt-pool states, powder-bed states, defect states |
| Inference      | Identified states                          | Failure causes, defect mechanisms, quality acceptance              |
| Evaluation     | Causes and responses                       | Risk, quality, melt-pool, thermal-field evaluation                 |
| Adaptation     | Evaluation results                         | Corrective actions, parameter changes, build-job updates           |
---
1. Runtime JSON / CSV / OPC UA / MQTT data
        ↓
2. Convert runtime data to LPBF_runtime_observation.ttl
        ↓
3. Run identification SPARQL rules
        ↓
4. Run inference SPARQL rules
        ↓
5. Run evaluation SPARQL rules
        ↓
6. Run adaptation SPARQL rules
        ↓
7. Generate LPBF_runtime_inferred.ttl
