"""merge conflicting migration heads

Revision ID: ebb0b6a07dc7
Revises: c4e8b3109d2a, e3477fa24581
Create Date: 2026-10-10 18:40:39.236808

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ebb0b6a07dc7'
down_revision: Union[str, Sequence[str], None] = ('c4e8b3109d2a', 'e3477fa24581')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
