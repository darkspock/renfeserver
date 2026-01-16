"""Create GTFS-RT alerts tables

Revision ID: 014
Revises: 013
Create Date: 2026-01-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '014'
down_revision: Union[str, None] = '013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enums if they don't exist
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE alertcauseenum AS ENUM (
                'UNKNOWN_CAUSE', 'OTHER_CAUSE', 'TECHNICAL_PROBLEM', 'STRIKE',
                'DEMONSTRATION', 'ACCIDENT', 'HOLIDAY', 'WEATHER', 'MAINTENANCE',
                'CONSTRUCTION', 'POLICE_ACTIVITY', 'MEDICAL_EMERGENCY'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE alerteffectenum AS ENUM (
                'NO_SERVICE', 'REDUCED_SERVICE', 'SIGNIFICANT_DELAYS', 'DETOUR',
                'ADDITIONAL_SERVICE', 'MODIFIED_SERVICE', 'OTHER_EFFECT',
                'UNKNOWN_EFFECT', 'STOP_MOVED'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create alerts table using raw SQL
    op.execute("""
        CREATE TABLE IF NOT EXISTS gtfs_rt_alerts (
            alert_id VARCHAR(100) PRIMARY KEY,
            cause alertcauseenum NOT NULL,
            effect alerteffectenum NOT NULL,
            header_text TEXT NOT NULL,
            description_text TEXT,
            url VARCHAR(500),
            active_period_start TIMESTAMP,
            active_period_end TIMESTAMP,
            timestamp TIMESTAMP NOT NULL,
            updated_at TIMESTAMP
        );
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_alerts_active_period
        ON gtfs_rt_alerts (active_period_start, active_period_end);
    """)

    # Create alert entities table
    op.execute("""
        CREATE TABLE IF NOT EXISTS gtfs_rt_alert_entities (
            id SERIAL PRIMARY KEY,
            alert_id VARCHAR(100) NOT NULL REFERENCES gtfs_rt_alerts(alert_id) ON DELETE CASCADE,
            route_id VARCHAR(100),
            stop_id VARCHAR(100),
            trip_id VARCHAR(100),
            agency_id VARCHAR(50),
            route_type INTEGER
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_gtfs_rt_alert_entities_alert_id ON gtfs_rt_alert_entities (alert_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_entities_route ON gtfs_rt_alert_entities (route_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_entities_stop ON gtfs_rt_alert_entities (stop_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gtfs_rt_alert_entities;")
    op.execute("DROP TABLE IF EXISTS gtfs_rt_alerts;")
    op.execute("DROP TYPE IF EXISTS alertcauseenum;")
    op.execute("DROP TYPE IF EXISTS alerteffectenum;")
