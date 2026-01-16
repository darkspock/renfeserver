"""Add route frequencies and alert source

Revision ID: 018
Revises: 017
Create Date: 2026-01-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '018'
down_revision: Union[str, None] = '017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create route frequencies table
    op.create_table(
        'gtfs_route_frequencies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('route_id', sa.String(100), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('headway_secs', sa.Integer(), nullable=False),
        sa.Column('day_type', sa.String(20), nullable=False, server_default='weekday'),
        sa.ForeignKeyConstraint(['route_id'], ['gtfs_routes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'ix_route_freq_lookup',
        'gtfs_route_frequencies',
        ['route_id', 'day_type', 'start_time']
    )
    op.create_index(
        'ix_route_freq_route_id',
        'gtfs_route_frequencies',
        ['route_id']
    )

    # Add source column to alerts table to distinguish manual vs automatic
    op.add_column(
        'gtfs_rt_alerts',
        sa.Column('source', sa.String(20), nullable=True, server_default='gtfsrt')
    )
    op.execute("UPDATE gtfs_rt_alerts SET source = 'gtfsrt' WHERE source IS NULL")


def downgrade() -> None:
    op.drop_column('gtfs_rt_alerts', 'source')
    op.drop_index('ix_route_freq_route_id', table_name='gtfs_route_frequencies')
    op.drop_index('ix_route_freq_lookup', table_name='gtfs_route_frequencies')
    op.drop_table('gtfs_route_frequencies')
