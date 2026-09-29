# Task: production-grade processing worker

Harden background processing for large LAS/LAZ→COPC jobs.

Acceptance criteria:
- Atomic job claim prevents two workers from running the same job.
- Jobs have attempt count, lease/heartbeat and retry policy.
- Processing is idempotent by project/version/source checksum.
- Failed jobs preserve actionable error and do not corrupt source objects.
- Worker uses scratch storage only for processing and cleans it in success/failure.
- Add concurrency/retry tests.
