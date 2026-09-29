---
name: pla-lidar-regression
description: Validate LiDAR ingestion, COPC conversion, pole mapping, and synchronized Plan/Profile/Cross/3D behavior against approved reference cases.
---

Use this skill for LiDAR/profile bugs, PDAL changes, CRS changes, block mapping, Potree changes, or engineering-view regressions.

1. Preserve source files and CRS metadata; never silently reproject.
2. Use non-production or explicitly approved test data.
3. Verify point count, bounds, dimensions, CRS, and block assignment before UI conclusions.
4. Validate Plan, Longitudinal Profile, Cross Section, and 3D Perspective for the same pole/span.
5. When profile math changes, compare at least one approved case against the Delivery team's MicroStation/TerraScan reference workflow.
6. Record tolerances from the customer/SOW or approved engineering decision; do not invent acceptance thresholds.
7. Run regression tests and summarize evidence.
