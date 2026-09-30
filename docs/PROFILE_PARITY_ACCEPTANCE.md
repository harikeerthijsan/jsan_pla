# PLA Profile / Section Parity Acceptance

This is the acceptance gate for changes to Plan, Longitudinal Profile, Cross Section, or 3D evidence.

## Reference workflow
Use Delivery-approved MicroStation + TerraScan output for the same source LiDAR and delivery workbook. The workbench profile uses a selected pole-to-pole axis:

- station: distance projected along the span axis
- offset: perpendicular distance from the span axis
- elevation: source/project Z

No acceptance tolerance is invented in software. Record the approved customer/Delivery tolerance for each project before sign-off.

## Minimum validation set
Use at least:
1. one normal two-pole span,
2. one dense attachment/crossarm pole,
3. one guy/anchor case,
4. one complex conductor span,
5. one source/pre-pop XY fallback case where delivery 3D is incomplete.

For every case compare:
- pole/span selection,
- CRS and project units,
- station at both poles,
- lateral offset direction,
- elevation,
- profile corridor width,
- cross-section station,
- visible conductor/attachment relationships,
- source LiDAR bounds/point count where relevant.

## Release evidence
Record dataset identifier, source version, CRS, selected poles, corridor settings, reference screenshots, reviewer, date, tolerance source, and PASS/FAIL result. Use non-production or explicitly approved customer data for regression evidence.

Start with `docs/examples/profile-parity-evidence.example.json`. Replace every placeholder and the zero corridor settings with approved staging values. Do not add tolerances until Delivery/customer approval identifies their source.

Validate the traceability record:

```powershell
python scripts/profile_parity_evidence.py validate path/to/evidence.json
```

After approved tolerances are recorded, produce a field-by-field comparison:

```powershell
python scripts/profile_parity_evidence.py compare path/to/evidence.json
```

The comparator exits `0` for PASS, `1` for an out-of-tolerance result, and `2` for invalid or incomplete evidence. It contains no default acceptance thresholds.
