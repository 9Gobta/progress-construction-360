"""add upper-floor shoring activities

Revision ID: d8a14c2e7b10
Revises: c2f94a6b7180
Create Date: 2026-09-09
"""

from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "d8a14c2e7b10"
down_revision: str | None = "c2f94a6b7180"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

activities = sa.table(
    "activities",
    sa.column("id", sa.Uuid()),
    sa.column("schedule_version_id", sa.Uuid()),
    sa.column("parent_activity_id", sa.Uuid()),
    sa.column("wbs", sa.String()),
    sa.column("name", sa.String()),
    sa.column("planned_start", sa.DateTime(timezone=True)),
    sa.column("planned_finish", sa.DateTime(timezone=True)),
    sa.column("percent_complete_source", sa.Numeric()),
    sa.column("is_summary", sa.Boolean()),
    sa.column("weight", sa.Numeric()),
    sa.column("source_row_no", sa.Integer()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
schedules = sa.table(
    "schedule_versions",
    sa.column("id", sa.Uuid()),
    sa.column("row_count", sa.Integer()),
)

SHORING_GROUPS = {"1": "คาน", "2": "พื้น", "4": "บันได"}


def _direct_rows(connection: sa.Connection, schedule_id: uuid.UUID, group_wbs: str):
    prefix = f"{group_wbs}."
    return [
        row
        for row in connection.execute(
            sa.select(activities).where(
                activities.c.schedule_version_id == schedule_id,
                activities.c.wbs.like(f"{prefix}%"),
                activities.c.is_summary.is_(False),
            ).order_by(activities.c.source_row_no, activities.c.wbs)
        ).mappings()
        if row["wbs"].startswith(prefix) and "." not in row["wbs"][len(prefix):]
    ]


def upgrade() -> None:
    connection = op.get_bind()
    schedule_ids = list(connection.scalars(sa.select(schedules.c.id)))
    for schedule_id in schedule_ids:
        added = 0
        for level in (2, 3, 4):
            for group_suffix, group_label in SHORING_GROUPS.items():
                group_wbs = f"1.2.{level}.{group_suffix}"
                rows = _direct_rows(connection, schedule_id, group_wbs)
                if not rows or any("ค้ำยัน" in row["name"] for row in rows):
                    continue
                suffixes = [row["wbs"].rsplit(".", 1)[1] for row in rows]
                if not all(suffix.isdigit() for suffix in suffixes):
                    continue
                shifted = []
                for row in rows:
                    temporary_wbs = f"__shoring_{uuid.uuid4().hex}"
                    shifted.append((row, temporary_wbs))
                    connection.execute(
                        sa.update(activities)
                        .where(activities.c.id == row["id"])
                        .values(wbs=temporary_wbs)
                    )
                for row, temporary_wbs in shifted:
                    suffix = int(row["wbs"].rsplit(".", 1)[1]) + 1
                    connection.execute(
                        sa.update(activities)
                        .where(activities.c.wbs == temporary_wbs)
                        .values(wbs=f"{group_wbs}.{suffix}")
                    )
                parent_id = connection.scalar(sa.select(activities.c.id).where(
                    activities.c.schedule_version_id == schedule_id,
                    activities.c.wbs == group_wbs,
                ))
                first = rows[0]
                connection.execute(sa.insert(activities).values(
                    id=uuid.uuid4(),
                    schedule_version_id=schedule_id,
                    parent_activity_id=parent_id,
                    wbs=f"{group_wbs}.1",
                    name=f"งานค้ำยัน{group_label}ชั้น {level}",
                    planned_start=first["planned_start"],
                    planned_finish=first["planned_finish"],
                    percent_complete_source=None,
                    is_summary=False,
                    weight=None,
                    source_row_no=first["source_row_no"],
                    created_at=datetime.now(timezone.utc),
                ))
                added += 1
        if added:
            connection.execute(
                sa.update(schedules)
                .where(schedules.c.id == schedule_id)
                .values(row_count=schedules.c.row_count + added)
            )


def downgrade() -> None:
    connection = op.get_bind()
    schedule_ids = list(connection.scalars(sa.select(schedules.c.id)))
    for schedule_id in schedule_ids:
        removed = 0
        for level in (2, 3, 4):
            for group_suffix, group_label in SHORING_GROUPS.items():
                group_wbs = f"1.2.{level}.{group_suffix}"
                shoring = connection.execute(sa.select(activities).where(
                    activities.c.schedule_version_id == schedule_id,
                    activities.c.wbs == f"{group_wbs}.1",
                    activities.c.name == f"งานค้ำยัน{group_label}ชั้น {level}",
                )).mappings().first()
                if shoring is None:
                    continue
                connection.execute(sa.delete(activities).where(activities.c.id == shoring["id"]))
                rows = _direct_rows(connection, schedule_id, group_wbs)
                shifted = []
                for row in rows:
                    suffix = row["wbs"].rsplit(".", 1)[1]
                    if not suffix.isdigit() or int(suffix) <= 1:
                        continue
                    temporary_wbs = f"__shoring_{uuid.uuid4().hex}"
                    shifted.append((row, temporary_wbs))
                    connection.execute(
                        sa.update(activities)
                        .where(activities.c.id == row["id"])
                        .values(wbs=temporary_wbs)
                    )
                for row, temporary_wbs in shifted:
                    suffix = int(row["wbs"].rsplit(".", 1)[1]) - 1
                    connection.execute(
                        sa.update(activities)
                        .where(activities.c.wbs == temporary_wbs)
                        .values(wbs=f"{group_wbs}.{suffix}")
                    )
                removed += 1
        if removed:
            connection.execute(
                sa.update(schedules)
                .where(schedules.c.id == schedule_id)
                .values(row_count=schedules.c.row_count - removed)
            )
