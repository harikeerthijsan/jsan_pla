# Task: linked Delivery Production and QC Production workspaces

Implement role-based Delivery and QC workspaces over the same project/dataset records. Do not create a second data silo.

Acceptance criteria:
- Header lets authorized users switch Delivery ↔ QC without re-login or re-upload.
- Delivery workspace shows dataset/revision status, processing state, correction queue, and resubmission action.
- QC workspace retains the existing four synchronized evidence views and findings.
- API authorizes actions by role; hiding a button is not authorization.
- Add tests for DELIVERY_USER, QC_REVIEWER, QC_LEAD, ADMIN.
- Existing ADMIN local workflow remains functional.
