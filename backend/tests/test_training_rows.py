from datetime import UTC, datetime

from sqlalchemy import select

from app.domain.models import TrainingRow


async def test_training_row_roundtrip(session_factory) -> None:
    features = {
        "restaurant_id": "00000000-0000-0000-0000-000000000001",
        "distance_km": 3.2,
        "hour_of_day": 20,
        "rain_intensity": 0.6,
    }
    completed_at = datetime(2026, 1, 5, 20, 30, tzinfo=UTC)

    async with session_factory() as session:
        session.add(
            TrainingRow(
                features_json=features,
                actual_prep_min=18.5,
                actual_drive_min=9.25,
                actual_total_min=27.75,
                completed_at=completed_at,
                source="history",
            )
        )
        await session.commit()

    async with session_factory() as session:
        stmt = select(TrainingRow).where(TrainingRow.source == "history")
        row = (await session.execute(stmt)).scalar_one()
        assert row.features_json == features
        assert row.features_json["hour_of_day"] == 20
        assert row.actual_prep_min == 18.5
        assert row.actual_drive_min == 9.25
        assert row.actual_total_min == 27.75
        assert row.source == "history"
        assert row.order_id is None
        assert row.completed_at == completed_at
        assert row.completed_at.tzinfo is not None
