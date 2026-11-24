"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class PeriodStatsPayload(BaseModel):
    """时段统计请求：hours 必参与取数，时段可由起点/终点或锚点+基准日确定。"""

    hours: float = 1
    period_start: str | None = None
    period_end: str | None = None
    anchor: str = "09:00"
    base_date: str | None = None


class DutyReportPayload(PeriodStatsPayload):
    generated_by: str = "值班长"


class QueryLogPayload(BaseModel):
    dataset: str
    query_summary: str = ""
    row_count: int = 0
    execution_time_ms: int = 0
    executor: str = "system"
    started_at: str | None = None
    ended_at: str | None = None
    executed_at: str | None = None
    registered_at: str | None = None


class DispatchPayload(BaseModel):
    query_log_id: int
    assignee: str = "值班工程师"
    note: str | None = None

