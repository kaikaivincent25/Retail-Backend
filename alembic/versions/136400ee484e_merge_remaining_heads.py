"""merge remaining heads

Revision ID: 136400ee484e
Revises: 062966d17f14, a14c5e8f9b22
Create Date: 2026-11-02 17:59:10.335002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '136400ee484e'
down_revision: Union[str, Sequence[str], None] = ('062966d17f14', 'a14c5e8f9b22')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
