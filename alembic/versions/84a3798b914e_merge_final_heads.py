"""merge final heads

Revision ID: 84a3798b914e
Revises: 136400ee484e, b31d7e4f6a90
Create Date: 2026-11-02 18:25:53.990823

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84a3798b914e'
down_revision: Union[str, Sequence[str], None] = ('136400ee484e', 'b31d7e4f6a90')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
