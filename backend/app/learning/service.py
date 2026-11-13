import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import joblib
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.exceptions import BadRequestError
from app.domain.models import ModelVersion, TrainingRow
from app.eta.engine import reset_engine_cache
from app.learning.trainer import DEFAULT_MIN_ROWS, TrainingDataError, train_model

logger = logging.getLogger(__name__)

MODEL_NAME = "eta"


@dataclass
class RetrainResult:
    version: str
    promoted: bool
    improved: bool
    metrics: dict
    active_version: str | None
    active_metrics: dict | None


async def _training_rows(session: AsyncSession) -> list:
    stmt = select(
        TrainingRow.features_json,
        TrainingRow.actual_prep_min,
        TrainingRow.actual_drive_min,
        TrainingRow.actual_total_min,
    )
    return list((await session.execute(stmt)).all())


async def active_version(session: AsyncSession) -> ModelVersion | None:
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.name == MODEL_NAME, ModelVersion.is_active.is_(True))
        .order_by(ModelVersion.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_versions(session: AsyncSession, limit: int = 50) -> list[ModelVersion]:
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.name == MODEL_NAME)
        .order_by(ModelVersion.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def _artifact_path(version: str, *, candidate: bool) -> Path:
    production = Path(settings.eta_model_path)
    if candidate:
        return production.parent / "candidates" / f"{version}.joblib"
    return production


def _write_bundle(bundle: dict, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp")
    joblib.dump(bundle, temp)
    temp.replace(path)
    return str(path)


async def retrain(
    session: AsyncSession,
    *,
    force: bool = False,
    min_rows: int = DEFAULT_MIN_ROWS,
) -> RetrainResult:
    rows = await _training_rows(session)
    try:
        bundle = await asyncio.to_thread(train_model, rows, min_rows=min_rows)
    except TrainingDataError as exc:
        raise BadRequestError(str(exc)) from exc

    metrics = bundle["metrics"]
    current = await active_version(session)
    current_mae = (
        float(current.metrics["total_mae"])
        if current is not None and "total_mae" in current.metrics
        else None
    )
    improved = current_mae is None or float(metrics["total_mae"]) < current_mae
    promoted = force or improved

    if promoted:
        artifact_path = _write_bundle(
            bundle, _artifact_path(bundle["version"], candidate=False)
        )
        await session.execute(
            update(ModelVersion)
            .where(ModelVersion.name == MODEL_NAME, ModelVersion.is_active.is_(True))
            .values(is_active=False)
        )
        record = ModelVersion(
            name=MODEL_NAME,
            version=bundle["version"],
            artifact_path=artifact_path,
            row_count=bundle["n_samples"],
            is_active=True,
            metrics=metrics,
        )
        session.add(record)
        await session.commit()
        reset_engine_cache()
        logger.info("promoted ETA model %s (total MAE %.2f)", record.version, metrics["total_mae"])
        active_version_name = record.version
        active_metrics = metrics
    else:
        artifact_path = _write_bundle(
            bundle, _artifact_path(bundle["version"], candidate=True)
        )
        record = ModelVersion(
            name=MODEL_NAME,
            version=bundle["version"],
            artifact_path=artifact_path,
            row_count=bundle["n_samples"],
            is_active=False,
            metrics=metrics,
        )
        session.add(record)
        await session.commit()
        logger.info(
            "kept ETA model %s (candidate MAE %.2f worse than active %.2f)",
            current.version if current is not None else "unknown",
            metrics["total_mae"],
            current_mae if current_mae is not None else -1.0,
        )
        active_version_name = current.version if current is not None else None
        active_metrics = current.metrics if current is not None else None

    return RetrainResult(
        version=record.version,
        promoted=promoted,
        improved=improved,
        metrics=metrics,
        active_version=active_version_name,
        active_metrics=active_metrics,
    )
