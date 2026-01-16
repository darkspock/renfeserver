"""Add platform column to GTFS-RT tables

Revision ID: 015
Revises: 014
Create Date: 2026-01-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '015'
down_revision: Union[str, None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add platform to stop_time_updates
    op.add_column(
        'gtfs_rt_stop_time_updates',
        sa.Column('platform', sa.String(20), nullable=True)
    )
    # Add platform to vehicle_positions
    op.add_column(
        'gtfs_rt_vehicle_positions',
        sa.Column('platform', sa.String(20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('gtfs_rt_stop_time_updates', 'platform')
    op.drop_column('gtfs_rt_vehicle_positions', 'platform')
