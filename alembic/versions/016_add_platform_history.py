"""Add platform history table for learning platform patterns

Revision ID: 016
Revises: 015
Create Date: 2026-01-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '016'
down_revision: Union[str, None] = '015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'gtfs_rt_platform_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('stop_id', sa.String(50), nullable=False),
        sa.Column('route_short_name', sa.String(20), nullable=False),
        sa.Column('headsign', sa.String(200), nullable=False),
        sa.Column('platform', sa.String(20), nullable=False),
        sa.Column('count', sa.Integer(), default=1),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
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


def downgrade() -> None:
    op.drop_index('ix_platform_history_stop', table_name='gtfs_rt_platform_history')
    op.drop_index('ix_platform_history_lookup', table_name='gtfs_rt_platform_history')
    op.drop_table('gtfs_rt_platform_history')
