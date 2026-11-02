"""merge heads

Revision ID: 062966d17f14
Revises: 9f2b7c1d4e6a, b8a536d56a58
Create Date: 2026-11-02 17:45:37.648930

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '062966d17f14'
down_revision: Union[str, Sequence[str], None] = ('9f2b7c1d4e6a', 'b8a536d56a58')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
