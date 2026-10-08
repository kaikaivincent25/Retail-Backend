"""merge M-Pesa and shop-wide session revisions

Revision ID: c0af3d5027a1
Revises: a37c6d9e41b2, de4a91f37b2c
Create Date: 2026-10-07 17:37:54.864068

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0af3d5027a1'
down_revision: Union[str, Sequence[str], None] = ('a37c6d9e41b2', 'de4a91f37b2c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
