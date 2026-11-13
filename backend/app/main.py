import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.assignment import router as assignment_router
from app.api.auth import router as auth_router
from app.api.customer import router as customer_router
from app.api.customers import router as customers_router
from app.api.health import router as health_router
from app.api.inbox import router as inbox_router
from app.api.learning import router as learning_router
from app.api.monitor import router as monitor_router
from app.api.orders import restaurant_router
from app.api.orders import router as orders_router
from app.api.realtime import router as realtime_router
from app.api.recs import router as recs_router
from app.api.restaurant_console import router as restaurant_console_router
from app.api.restaurants import router as restaurants_router
from app.api.rider import router as rider_router
from app.api.riders import router as riders_router
from app.api.ws_marketplace import router as ws_marketplace_router
from app.config import settings
from app.db import get_sessionmaker
from app.domain.exceptions import BadRequestError, ConflictError, NotFoundError
from app.marketplace import dispatch

logger = logging.getLogger(__name__)


async def _offer_sweeper() -> None:
    """Advance timed-out rider offers without relying on an open browser."""
    while True:
        try:
            async with get_sessionmaker()() as session:
                await dispatch.sweep_expired_offers(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("dispatch offer sweep failed")
        await asyncio.sleep(settings.offer_sweep_interval_s)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_offer_sweeper())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(BadRequestError)
async def bad_request_handler(request: Request, exc: BadRequestError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(health_router)
app.include_router(restaurants_router)
app.include_router(customers_router)
app.include_router(riders_router)
app.include_router(orders_router)
app.include_router(restaurant_router)
app.include_router(assignment_router)
app.include_router(monitor_router)
app.include_router(learning_router)
app.include_router(recs_router)
app.include_router(realtime_router)
app.include_router(auth_router)
app.include_router(customer_router)
app.include_router(rider_router)
app.include_router(restaurant_console_router)
app.include_router(inbox_router)
app.include_router(ws_marketplace_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs", "health": "/healthz"}
