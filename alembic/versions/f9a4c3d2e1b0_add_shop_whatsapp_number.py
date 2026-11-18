"""add shop WhatsApp contact number"""

from alembic import op
import sqlalchemy as sa


revision = "f9a4c3d2e1b0"
down_revision = "e8f4a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("whatsapp_number", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("shops", "whatsapp_number")
