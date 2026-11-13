import logging
import os
from collections.abc import Mapping

from app.config import settings
from app.eta.fallback import fallback_eta
from app.eta.model import EtaEngine
from app.eta.types import EtaPrediction

logger = logging.getLogger(__name__)

_engine_cache: dict[str, tuple[float, EtaEngine | None]] = {}


def _load_engine(path: str) -> EtaEngine | None:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None

    cached = _engine_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    engine: EtaEngine | None = None
    try:
        engine = EtaEngine.load(path)
        logger.info("loaded ETA model %s (%s)", path, engine.version)
    except Exception as exc:  # noqa: BLE001 - model files are untrusted at startup
        logger.warning("could not load ETA model from %s: %s", path, exc)
    _engine_cache[path] = (mtime, engine)
    return engine


def predict_eta(features: Mapping[str, float]) -> EtaPrediction:
    """Predict an ETA, never raising: falls back to the heuristic on any failure."""
    engine = _load_engine(settings.eta_model_path)
    if engine is not None:
        try:
            return engine.predict(features)
        except Exception as exc:  # noqa: BLE001 - ETA must never fail
            logger.warning("ETA model inference failed, using fallback: %s", exc)
    return fallback_eta(features)


def reset_engine_cache() -> None:
    _engine_cache.clear()
