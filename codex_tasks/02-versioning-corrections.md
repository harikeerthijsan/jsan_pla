# Task: dataset versions and correction lifecycle

Add dataset versions, QC runs tied to a version, correction requests, and revision comparison.

Statuses: UPLOADING, PROCESSING, READY_FOR_QC, QC_IN_PROGRESS, CORRECTION_REQUIRED, RESUBMITTED, APPROVED, ARCHIVED.

Acceptance criteria:
- Source files are immutable per version.
- Findings reference exact version + QC run.
- QC can Send for correction with comment; Delivery sees queue.
- New version can classify prior findings as RESOLVED, STILL_OPEN, or NEW without rewriting history.
- Audit every transition.
- Include migration and regression tests.
