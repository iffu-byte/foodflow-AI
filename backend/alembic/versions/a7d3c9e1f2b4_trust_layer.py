"""trust layer: delivery proof, portions, nutrition, kitchen reality, rescue, batching

Revision ID: a7d3c9e1f2b4
Revises: e6a4f91b2d77
Create Date: 2026-11-14 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d3c9e1f2b4"
down_revision: str | None = "e6a4f91b2d77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("daily_kcal_goal", sa.Integer(), nullable=True))

    op.add_column("restaurants", sa.Column("fssai_license", sa.String(20), nullable=True))
    op.add_column("restaurants", sa.Column("fssai_valid_until", sa.Date(), nullable=True))
    op.add_column(
        "restaurants",
        sa.Column("kitchen_type", sa.String(20), nullable=False, server_default="dine_in"),
    )
    op.add_column(
        "restaurants",
        sa.Column("price_parity", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("restaurants", sa.Column("google_place_id", sa.String(160), nullable=True))
    op.add_column(
        "restaurants",
        sa.Column(
            "place_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "restaurants",
        sa.Column("place_checked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("menu_items", sa.Column("portion_grams", sa.Integer(), nullable=True))
    op.add_column("menu_items", sa.Column("portion_serves", sa.Integer(), nullable=True))
    op.add_column("menu_items", sa.Column("portion_pieces", sa.Integer(), nullable=True))
    op.add_column(
        "menu_items",
        sa.Column("portion_method", sa.String(20), nullable=False, server_default="unknown"),
    )
    op.add_column("menu_items", sa.Column("portion_confidence", sa.Float(), nullable=True))
    op.add_column("menu_items", sa.Column("portion_photo_url", sa.String(500), nullable=True))
    op.add_column(
        "menu_items",
        sa.Column("portion_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "menu_items",
        sa.Column(
            "ingredients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "menu_items",
        sa.Column(
            "nutrition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.add_column("orders", sa.Column("delivery_otp", sa.String(6), nullable=True))
    op.add_column(
        "orders", sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "orders",
        sa.Column(
            "delivery_proof",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "orders",
        sa.Column("delivery_mode", sa.String(10), nullable=False, server_default="solo"),
    )
    op.add_column(
        "orders",
        sa.Column("shared_saving", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )
    op.add_column("orders", sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("orders", sa.Column("batch_sequence", sa.Integer(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("compensation", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )
    op.add_column(
        "orders",
        sa.Column(
            "delay_attribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_orders_batch", "orders", ["batch_id"])

    op.add_column("reviews", sa.Column("quantity_feedback", sa.String(16), nullable=True))

    op.create_table(
        "kitchen_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("caption", sa.String(160), nullable=False, server_default=""),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_kitchen_photos_restaurant_taken", "kitchen_photos", ["restaurant_id", "taken_at"]
    )

    op.create_table(
        "rescue_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "menu_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("menu_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("qty_total", sa.Integer(), nullable=False),
        sa.Column("qty_left", sa.Integer(), nullable=False),
        sa.Column("original_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("start_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("floor_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="LIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("qty_left >= 0", name="ck_rescue_listings_qty_left"),
        sa.CheckConstraint("floor_price > 0", name="ck_rescue_listings_floor_price"),
    )
    op.create_index("ix_rescue_listings_restaurant_id", "rescue_listings", ["restaurant_id"])
    op.create_index("ix_rescue_listings_status_ends", "rescue_listings", ["status", "ends_at"])

    op.add_column(
        "cart_items",
        sa.Column(
            "rescue_listing_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("rescue_listings.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "prep_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "menu_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("menu_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("prepared_qty", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("restaurant_id", "menu_item_id", "day", name="uq_prep_log_item_day"),
    )
    op.create_index("ix_prep_logs_restaurant_id", "prep_logs", ["restaurant_id"])

    op.create_table(
        "ai_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("est_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("detail", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_usage_created", "ai_usage", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_created", table_name="ai_usage")
    op.drop_table("ai_usage")
    op.drop_index("ix_prep_logs_restaurant_id", table_name="prep_logs")
    op.drop_table("prep_logs")
    op.drop_column("cart_items", "rescue_listing_id")
    op.drop_index("ix_rescue_listings_status_ends", table_name="rescue_listings")
    op.drop_index("ix_rescue_listings_restaurant_id", table_name="rescue_listings")
    op.drop_table("rescue_listings")
    op.drop_index("ix_kitchen_photos_restaurant_taken", table_name="kitchen_photos")
    op.drop_table("kitchen_photos")
    op.drop_column("reviews", "quantity_feedback")
    op.drop_index("ix_orders_batch", table_name="orders")
    for column in (
        "delay_attribution",
        "compensation",
        "batch_sequence",
        "batch_id",
        "shared_saving",
        "delivery_mode",
        "delivery_proof",
        "otp_attempts",
        "delivery_otp",
    ):
        op.drop_column("orders", column)
    for column in (
        "nutrition",
        "ingredients",
        "portion_verified_at",
        "portion_photo_url",
        "portion_confidence",
        "portion_method",
        "portion_pieces",
        "portion_serves",
        "portion_grams",
    ):
        op.drop_column("menu_items", column)
    for column in (
        "place_checked_at",
        "place_snapshot",
        "google_place_id",
        "price_parity",
        "kitchen_type",
        "fssai_valid_until",
        "fssai_license",
    ):
        op.drop_column("restaurants", column)
    op.drop_column("customers", "daily_kcal_goal")
