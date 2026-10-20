"""merge multiple heads

Revision ID: bce8b3542098
Revises: 2d6f8a1c4b90, 4f9c8a2d1e6b
Create Date: 2026-10-20 21:03:20.208953

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bce8b3542098'
down_revision: Union[str, Sequence[str], None] = ('2d6f8a1c4b90', '4f9c8a2d1e6b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
