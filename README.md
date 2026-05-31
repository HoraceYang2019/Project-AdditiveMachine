### Ontology Development
1. **Prepare ontology**:
   
   location: ontology/MC_ontology_*.ttl

---
2. **Prepare editable component \ batch thresholds**:
   
   location: knowledge/thresholds_component.csv \ batch_*.csv

3. **Generate component \batch knowledge TTL**:
   
   location: knowledge/component_threshold_knowledge.ttl \ batch_*.ttl
  > python scripts/generate_batch_ttl_from_threshold_csv.py <br>
  > python scripts/generate_sth_ttl_from_threshold_csv.py
  
  *Validate inferred TTL:* location: shapes\MC_gerated_shapes.ttl
  > python scripts/generate_cnc_generated_shapes.py

---  
4. **Prepare runtime observation json**:
   
   location: sample/_runtime_w10233.json

   
5.  **Generate runtime observation TTL**:
  
  location: runtime/MC_runtime_observation.ttl 
  > python runtime/runtime_observation_ttl_from_windows_json_multi.py <br>
  
   *Validate inferred TTL: shapes\MC_generated_shapes.ttl*

---
6. **Prepare SPARQL inference**:<br>
  location: rules/01_infer_tool_condition.rq <br>

  *Validate inferred TTL: shapes\MC_generated_shapes.ttl*


7. **Run inference**:
   > python rdf_native_infer_sparql.py
---
###
[20260601] updated
Add the five stages: sensing, identifying, inference, evaluation, and adaptation to the ontology 
1. The sensing stage has the location of a laser spot, flow, and images of chamber and laser-roi.
2. The identification stage uses the sensing data to identify states of processing (normal, alarm, and fault), and states of meltpool, coating, and spatter
3. The inference stage infers failure causes and responses of filter and quality (accepted, margin, and reject) based on identified states.
4. The evaluation stage evaluates the meltpool width, length, and depth, and quality based on the responses of causes.
5. The adaptation stage suggests process management with components and scan-path changed.
