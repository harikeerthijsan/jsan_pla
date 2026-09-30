# Task: CI/CD and environment release gates

Implement GitHub CI plus safe preview/staging/production promotion for Railway + Vercel.

Acceptance criteria:
- PR runs pytest, compileall, JS syntax and image builds.
- PR/Preview cannot use production DB/bucket credentials.
- Staging is persistent and isolated.
- Production deployment requires checks and uses /health/ready.
- Document rollback.
- No provider tokens committed to Git.
