"""Persist CAP-023 canvas in PostgreSQL.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from datetime import datetime, timezone


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    table = sa.table(
        "canvas_documents",
        sa.column("id", sa.String),
        sa.column("version", sa.Integer),
        sa.column("nodes", sa.JSON),
        sa.column("edges", sa.JSON),
        sa.column("snapshot", sa.JSON),
        sa.column("updated_by", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    if not sa.inspect(bind).has_table("canvas_documents"):
        op.create_table(
            "canvas_documents",
            sa.Column("id", sa.String(length=80), primary_key=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("nodes", sa.JSON(), nullable=False),
            sa.Column("edges", sa.JSON(), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("updated_by", sa.String(length=200), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if bind.execute(sa.select(table.c.id).where(table.c.id == "primary")).first() is None:
        op.bulk_insert(
            table,
            [
                {
                    "id": "primary",
                    "version": 0,
                    "nodes": [
                        {"id": "D1", "x": 40, "y": 60, "w": 150, "h": 60, "text": "D1 Komunikácia", "color": "green"},
                        {"id": "D4", "x": 220, "y": 60, "w": 150, "h": 60, "text": "D4 Produkcia", "color": "green"},
                        {"id": "D5", "x": 400, "y": 60, "w": 150, "h": 60, "text": "D5 Kvalita", "color": "green"},
                        {"id": "D7", "x": 580, "y": 60, "w": 150, "h": 60, "text": "D7 Riadenie", "color": "green"},
                        {"id": "D2", "x": 130, "y": 180, "w": 150, "h": 60, "text": "D2 Šírenie", "color": "amber"},
                        {"id": "D3", "x": 310, "y": 180, "w": 150, "h": 60, "text": "D3 Financie", "color": "amber"},
                        {"id": "D6", "x": 490, "y": 180, "w": 150, "h": 60, "text": "D6 Verejnosť", "color": "amber"},
                    ],
                    "edges": [
                        {"from": "D1", "to": "D2"},
                        {"from": "D4", "to": "D3"},
                        {"from": "D5", "to": "D6"},
                    ],
                    "snapshot": {},
                    "updated_by": "system",
                    "updated_at": datetime.now(timezone.utc),
                }
            ],
        )


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("canvas_documents"):
        op.drop_table("canvas_documents")
