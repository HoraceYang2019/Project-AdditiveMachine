| Defect Type| Physical Mechanism| Primary Process Variable Cause| 
| ---|--- |---- | 
| Lack of Fusion| Incomplete melting and poor layer adhesion|Energy Density too low / Hatch spacing too wide | 
| Keyhole Pores| Vapor cavity collapse trapping gas|Energy Density too high | 
| Balling| Marangoni instability / Scanning speed too high| Surface tension| 
| Cracking/Warping| Extreme residual stress build-up| Severe thermal gradients| 
| Streaks/Voids| Mechanical disruption of the powder bed |Damaged recoater blade / Short powder supply| 


| Defect Type| Responses| 
| ---|--- |
| Lack of Fusion| Increase Volumetric Energy Density ($VED$): Increase the laser power ($P$) or decrease the scanning speed ($v$) to ensure the laser delivers enough heat to thoroughly melt both the raw powder and the underlying solid layer.
||Reduce Hatch Spacing: Narrow the distance between parallel laser tracks to ensure sufficient overlap, preventing unmelted gaps between lines.|
||Reduce Layer Thickness: Thin out the powder layer if the laser cannot penetrate deep enough to fuse with the previous layer.| 
| Keyhole Pores| Decrease Volumetric Energy Density: Decrease laser power or increase scanning speed to prevent the metal from reaching its boiling point and forming a deep vapor cavity.| 
|| Optimize Laser Profile: Use a "skywriting" feature (where the laser turns off or adjusts power during acceleration/deceleration at the ends of a scan line) to prevent heat from stacking up at the turnarounds.|
| Balling| Adjust the $P/v$ Ratio: Ensure the scanning speed is not disproportionately high compared to the laser power. Keeping the melt pool stable prevents capillary forces from breaking it up into isolated spheres.|
||Atmosphere Control: Maintain strict control over the inert gas (Argon or Nitrogen) purity. Oxygen levels should be kept extremely low (typically $< 100 \text{ ppm}$) to prevent oxide films from forming on the liquid metal, which ruins wettability.| 
| Warping| Baseplate Preheating: Heat the build plate (typically between 100°C and 200°C, and up to 500°C+ for crack-prone materials like titanium or tool steels). This narrows the temperature gap between the molten pool and the rest of the part, drastically reducing residual stress.|
||Sacrificial Support Structures: Design robust anchor supports to mechanically hold the part down to the build plate, physically preventing it from curling or lifting.|
|| Rescanning / In-situ Annealing: Use the laser to quickly scan the layer a second time at a lower power immediately after melting. This acts as a localized heat treatment to relieve stress before the next layer is applied| 
| Cracking|Alloy Modification: Introduce minor alloying elements (like adding Silicon to Aluminum alloys) to alter the solidification range and close liquid films faster.|
||Grain Refinement: Use nucleating agents to promote a fine, equiaxial grain structure rather than long, columnar grains, which are highly susceptible to tearing.| 
||Spatter and Soot Control: |Optimize Gas Flow Velocity: Fine-tune the laminar cross-flow of inert gas across the powder bed to ensure it is strong enough to immediately sweep away airborne spatter and soot before they can fall back onto the build area. |
||Alter Scan Direction: Program the laser to scan against the direction of the gas flow so that any generated soot is blown away from the path the laser is about to take.|
| Streaks/Voids| Soft Recoater Blades: Use flexible silicone or carbon-fiber brush recoater blades instead of rigid HSS (High-Speed Steel) or ceramic blades. If a part warps slightly, a soft blade will bend over it rather than crashing or chipping.|
||Increase Delivery Factor: Set the powder delivery dosing factor higher (e.g., dispensing $120\%\text{ to }140\%$ of the required layer volume) to guarantee the recoater never runs out of powder mid-stroke. |
