"""Super admin role: existing admins keep working from anywhere.

Admins used to be exempt from the office-network rule. They now follow their own remote_access switch (set by a
super admin), so every existing admin starts with "anywhere" and nobody is locked out by the upgrade.

Revision ID: 20261008_0013
Revises: 20261007_0012
"""

import sqlalchemy as sa
from alembic import op


revision = "20261008_0013"
down_revision = "20261007_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE users SET remote_access = :yes WHERE upper(role) = 'ADMIN'").bindparams(yes=True))


def downgrade() -> None:
    # Older releases ignore remote_access for admins; nothing to undo.
    pass
