"""Add observation_date to platform history

Revision ID: 017
Revises: 016
Create Date: 2026-01-16

"""
from typing import Sequence, Union
from datetime import date

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '017'
down_revision: Union[str, None] = '016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add observation_date column with default today
    op.add_column(
        'gtfs_rt_platform_history',
        sa.Column('observation_date', sa.Date(), nullable=True)
    )

    # Set existing records to today's date
    op.execute(f"UPDATE gtfs_rt_platform_history SET observation_date = CURRENT_DATE")

    # Make column not nullable
    op.alter_column('gtfs_rt_platform_history', 'observation_date', nullable=False)

    # Drop old indexes
    op.drop_index('ix_platform_history_lookup', table_name='gtfs_rt_platform_history')
    op.drop_index('ix_platform_history_stop', table_name='gtfs_rt_platform_history')

    # Create new indexes including date
    op.create_index(
        'ix_platform_history_lookup',
        'gtfs_rt_platform_history',
        ['stop_id', 'route_short_name', 'headsign', 'observation_date']
    )
    op.create_index(
        'ix_platform_history_stop_date',
        'gtfs_rt_platform_history',
        ['stop_id', 'observation_date']
    )


def downgrade() -> None:
    op.drop_index('ix_platform_history_stop_date', table_name='gtfs_rt_platform_history')
    op.drop_index('ix_platform_history_lookup', table_name='gtfs_rt_platform_history')
    op.drop_column('gtfs_rt_platform_history', 'observation_date')
    op.create_index(
        'ix_platform_history_lookup',
        'gtfs_rt_platform_history',
        ['stop_id', 'route_short_name', 'headsign']
    )
    op.create_index(
        'ix_platform_history_stop',
        'gtfs_rt_platform_history',
        ['stop_id']
    )
