from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep
from app.auth.deps import require_roles
from app.domain.models import Role
from app.domain.schemas import OrderOut, RiderOut
from app.monitor import service as monitor_service
from app.monitor.schemas import MonitorSummaryOut, RiskOrderOut, ScanOut

router = APIRouter(
    prefix="/monitor",
    tags=["monitor"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
)


def _risk_out(item: monitor_service.RiskItem) -> RiskOrderOut:
    return RiskOrderOut(
        order=OrderOut.model_validate(item.order),
        rider=(
            RiderOut.model_validate(item.rider) if item.rider is not None else None
        ),
        severity=item.severity,
        flags=item.flags,
        minutes_remaining=item.minutes_remaining,
        minutes_since_last_event=item.minutes_since_last_event,
        risk_score=item.risk_score,
        reasons=item.reasons,
    )


@router.get("/at-risk", response_model=list[RiskOrderOut])
async def list_at_risk(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RiskOrderOut]:
    items = await monitor_service.list_at_risk(session, limit=limit)
    return [_risk_out(item) for item in items]


@router.post("/scan", response_model=ScanOut)
async def scan_orders(
    session: SessionDep,
    limit: int = Query(default=200, ge=1, le=500),
) -> ScanOut:
    result = await monitor_service.scan(session, limit=limit)
    return ScanOut(
        scanned=result.scanned,
        flagged=len(result.orders),
        events_appended=result.events_appended,
        orders=[_risk_out(item) for item in result.orders],
    )


@router.get("/summary", response_model=MonitorSummaryOut)
async def monitor_summary(session: SessionDep) -> MonitorSummaryOut:
    result = await monitor_service.summary(session)
    return MonitorSummaryOut(
        active_orders=result.active_orders,
        at_risk=result.at_risk,
        late=result.late,
        stalled=result.stalled,
        avg_minutes_remaining=result.avg_minutes_remaining,
    )
