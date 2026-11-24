"""查询历史时段统计与值班报告路由：先于通用资源路由注册，避免被 /{module}/{id} 抢占。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    DispatchPayload, DutyReportPayload, PeriodStatsPayload, QueryLogPayload,
)
from app.services import service_for

router = APIRouter(prefix="/api/query_history", tags=["查询历史值班报告"])


def _service():
    service = service_for("query_history")
    if service is None:
        raise HTTPException(status_code=500, detail="查询历史服务未注册")
    return service


@router.get("/period-stats")
def get_period_stats(
    hours: float = Query(default=1),
    period_start: str | None = Query(default=None),
    period_end: str | None = Query(default=None),
    anchor: str = Query(default="09:00"),
    base_date: str | None = Query(default=None),
) -> dict:
    """从查询历史列表发起时段统计；hours 与时段参数真实参与取数。"""
    try:
        return _service().period_stats(
            hours, period_start=period_start, period_end=period_end,
            anchor=anchor, base_date=base_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/period-stats")
def post_period_stats(payload: PeriodStatsPayload) -> dict:
    try:
        return _service().period_stats(
            payload.hours, period_start=payload.period_start,
            period_end=payload.period_end, anchor=payload.anchor,
            base_date=payload.base_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/period-stats/issue-report")
def issue_duty_report(payload: DutyReportPayload) -> dict:
    """按本次时段统计签发值班报告，冻结慢查询明细与平均耗时范围。"""
    try:
        return _service().issue_duty_report(
            payload.hours, period_start=payload.period_start,
            period_end=payload.period_end, anchor=payload.anchor,
            base_date=payload.base_date, generated_by=payload.generated_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/period-stats/reports")
def list_duty_reports(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    reports = _service().list_duty_reports(limit=limit)
    return {"items": reports, "total": len(reports)}


@router.get("/period-stats/reports/{report_id}")
def get_duty_report(report_id: int) -> dict:
    detail = _service().duty_report_detail(report_id)
    if not detail.get("ok", True):
        raise HTTPException(status_code=404, detail=detail.get("message", "报告不存在"))
    return detail


@router.post("/period-stats/reports/{report_id}/dispatch")
def dispatch_slow_query(report_id: int, payload: DispatchPayload) -> dict:
    return _service().dispatch_slow_query(
        report_id, payload.query_log_id, payload.assignee, payload.note)


@router.get("/period-stats/coverage/{query_log_id}")
def explain_coverage(query_log_id: int) -> dict:
    result = _service().explain_report_coverage(query_log_id)
    if not result.get("ok", True):
        raise HTTPException(status_code=404, detail=result.get("message", "查询不存在"))
    return result


@router.post("/logs")
def register_query_log(payload: QueryLogPayload) -> dict:
    """补登查询日志；迟到登记不会改写已签发报告。"""
    result = _service().record_query(
        dataset=payload.dataset,
        query_summary=payload.query_summary,
        row_count=payload.row_count,
        execution_time_ms=payload.execution_time_ms,
        executor=payload.executor,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        executed_at=payload.executed_at,
        registered_at=payload.registered_at,
    )
    return {"ok": True, **result}
