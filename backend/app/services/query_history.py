"""查询历史领域服务：记录和审计所有分析查询的调用链路和性能。

真实数据流：每次分析查询调用 → 记录查询时间/执行人/涉及数据集/查询摘要/返回行数/耗时
→ 写入 query_log 表 → 自动标记慢查询（> 500ms）和超时（> 30s）。

时段统计口径（明细、平均值、计数必须一致）：
- 一条查询按 **结束时间** 归属时段，时段区间为 ``[period_start, period_end)``。
- 跨过时段起点的查询（开始早于起点、结束落在时段内）归入本时段，
  归属依据保留为 ``ended_at`` / ``executed_at``，并在归属原因里写清楚跨界事实。
- 老查询缺少开始时间时，用可验证的结束时间（executed_at）归属，并标注依据。
- 值班报告签发时把统计结果、慢查询编号、平均耗时范围和全部日志编号冻结；
  之后补登的查询不会改写已签发报告，只会在详情里解释“为什么这份报告没有它”。
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any

from app.database import db
from app.services.base import BaseModuleService

PERIOD_ANCHOR = "09:00"
SLOW_STATUSES = ("慢查询", "超时终止")
_TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def parse_timestamp(value: Any) -> datetime | None:
    """把数据库/接口里的时间统一解析成无时区的本地时间。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
            for fmt in _TIMESTAMP_FORMATS:
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def format_timestamp(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S") if value else ""


def _parse_anchor(anchor: str | None) -> time:
    text = (anchor or PERIOD_ANCHOR).strip()
    try:
        parsed = datetime.strptime(text, "%H:%M").time()
    except ValueError:
        parsed = datetime.strptime(PERIOD_ANCHOR, "%H:%M").time()
    return parsed


def resolve_period(
    hours: float | int | str | None = 1,
    *,
    period_start: str | datetime | None = None,
    period_end: str | datetime | None = None,
    anchor: str = PERIOD_ANCHOR,
    base_date: str | date | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime, float]:
    """解析本次请求的时段。

    优先使用显式 ``period_start``；只给 ``period_end`` 时向前推 ``hours``；
    都不给时锚定到 ``anchor``（默认 09:00），跨天取最近一个还没到的锚点。
    """
    try:
        hours_value = float(hours) if hours not in (None, "") else 1.0
    except (TypeError, ValueError):
        raise ValueError("小时数必须是数字")
    if hours_value <= 0:
        raise ValueError("小时数必须大于 0")

    start = parse_timestamp(period_start)
    end = parse_timestamp(period_end)

    if start is not None and end is not None:
        pass
    elif start is not None:
        end = start + timedelta(hours=hours_value)
    elif end is not None:
        start = end - timedelta(hours=hours_value)
    else:
        current = parse_timestamp(now) or datetime.now()
        if base_date is not None:
            if isinstance(base_date, date):
                day = base_date
            else:
                parsed_day = parse_timestamp(base_date)
                if parsed_day is None:
                    raise ValueError("基准日期格式不正确")
                day = parsed_day.date()
        else:
            day = current.date()
        start = datetime.combine(day, _parse_anchor(anchor))
        if base_date is None and start > current:
            start -= timedelta(days=1)
        end = start + timedelta(hours=hours_value)

    if end <= start:
        raise ValueError("时段的结束时间必须晚于开始时间")
    actual_hours = round((end - start).total_seconds() / 3600, 4)
    return start, end, actual_hours


class QueryHistoryService(BaseModuleService):
    MODULE = "query_history"
    ENTITY = "查询记录"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["查询时间", "执行人", "涉及数据集", "查询语句摘要", "返回行数"]
    REQUIRED_FIELDS = ["查询时间", "执行人", "涉及数据集"]
    STATUS_ORDER = ["正常", "慢查询", "超时终止"]
    ACTION_RULES = {"标记慢查询": "慢查询", "重新执行": "正常"}
    NEGATIVE_ACTIONS: list[str] = []

    # ================================================================
    # 查询登记
    # ================================================================

    def record_query(
        self, dataset: str, query_summary: str, row_count: int,
        execution_time_ms: int, executor: str = "system",
        *, started_at: Any = None, ended_at: Any = None,
        executed_at: Any = None, registered_at: Any = None,
    ) -> dict[str, Any]:
        """记录一条查询日志，保留开始/结束时间用于时段归属。"""
        status = self._status_for(execution_time_ms)
        start = parse_timestamp(started_at)
        end = parse_timestamp(ended_at)
        registered = parse_timestamp(registered_at) or datetime.now()
        # executed_at 兼容旧字段，语义是“可验证的查询执行时间”；
        # 只有显式给了 ended_at 才写入结束时间，避免把执行时间伪装成结束时间。
        executed = parse_timestamp(executed_at) or end or registered

        log_id = db.insert("query_log", {
            "executor": executor,
            "dataset": dataset,
            "query_summary": query_summary,
            "row_count": row_count,
            "execution_time_ms": execution_time_ms,
            "status": status,
            "executed_at": format_timestamp(executed),
            "started_at": format_timestamp(start) or None,
            "ended_at": format_timestamp(end) or None,
            "registered_at": format_timestamp(registered),
        })
        return {"id": log_id, "status": status}

    def set_status(self, entry_id: int, status: str) -> dict[str, Any] | None:
        """标记慢查询/恢复正常；不改动已有的时间归属信息。"""
        db.update("query_log", {"status": status}, "id=?", [entry_id])
        return db.fetchone("SELECT * FROM query_log WHERE id=?", [entry_id])

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """通用登记入口：接受中文时间字段并补齐可归属的时间。"""
        mapped = dict(values)
        if "查询时间" in mapped and "executed_at" not in mapped:
            mapped["executed_at"] = mapped.get("查询时间")
        if "开始时间" in mapped and "started_at" not in mapped:
            mapped["started_at"] = mapped.get("开始时间")
        if "结束时间" in mapped and "ended_at" not in mapped:
            mapped["ended_at"] = mapped.get("结束时间")
        if "耗时毫秒" in mapped and "execution_time_ms" not in mapped:
            mapped["execution_time_ms"] = mapped.get("耗时毫秒")
        if "执行时间毫秒" in mapped and "execution_time_ms" not in mapped:
            mapped["execution_time_ms"] = mapped.get("执行时间毫秒")

        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing

        try:
            duration = int(float(mapped.get("execution_time_ms") or 0))
        except (TypeError, ValueError):
            duration = 0
        try:
            row_count = int(float(values.get("返回行数") or 0))
        except (TypeError, ValueError):
            row_count = 0

        entry = self.record_query(
            dataset=str(values.get("涉及数据集") or ""),
            query_summary=str(values.get("查询语句摘要") or ""),
            row_count=row_count,
            execution_time_ms=duration,
            executor=str(values.get("执行人") or "system"),
            started_at=mapped.get("started_at"),
            ended_at=mapped.get("ended_at"),
            executed_at=mapped.get("executed_at"),
            registered_at=mapped.get("registered_at"),
        )
        return db.fetchone("SELECT * FROM query_log WHERE id=?", [entry["id"]]), []

    @staticmethod
    def _status_for(execution_time_ms: int) -> str:
        if execution_time_ms > 30000:
            return "超时终止"
        if execution_time_ms > 500:
            return "慢查询"
        return "正常"

    # ================================================================
    # 时段归属
    # ================================================================

    def _describe_attribution(
        self, start: datetime | None, end: datetime | None,
        period_start: datetime, period_end: datetime,
        time_source: str = "ended_at",
    ) -> dict[str, Any]:
        """为一条查询生成可核对的归属依据与原因。

        ``time_source`` 说明 ``end`` 来自 ``ended_at`` 还是旧字段 ``executed_at``，
        保证“归属依据”与真实取数字段一致。
        """
        if end is None:
            return {
                "in_period": False,
                "attribution_basis": None,
                "attribution_reason": "缺少可验证的结束时间，无法归属到任何时段",
                "effective_time": None,
            }

        in_period = period_start <= end < period_end
        basis = time_source
        if start is not None and start < period_start <= end:
            reason = (
                f"查询开始 {format_timestamp(start)} 早于时段起点 "
                f"{format_timestamp(period_start)}，结束 {format_timestamp(end)} "
                f"落在本时段，按结束时间归属"
            )
            basis = f"{time_source}_crossing_start"
        elif start is None:
            reason = (
                f"缺少开始时间，按可验证的{'结束' if time_source == 'ended_at' else '执行'}"
                f"时间 {format_timestamp(end)} 归属"
            )
            basis = f"{time_source}_missing_start"
        elif in_period:
            reason = f"结束时间 {format_timestamp(end)} 落在本时段"
        elif end < period_start:
            reason = (
                f"结束时间 {format_timestamp(end)} 早于时段起点 "
                f"{format_timestamp(period_start)}，不属于本时段"
            )
        else:
            reason = (
                f"结束时间 {format_timestamp(end)} 不早于时段终点 "
                f"{format_timestamp(period_end)}，不属于本时段"
            )

        return {
            "in_period": in_period,
            "attribution_basis": basis,
            "attribution_reason": reason,
            "effective_time": format_timestamp(end),
        }

    def _query_detail(
        self, row: dict[str, Any], period_start: datetime, period_end: datetime,
    ) -> dict[str, Any]:
        started = parse_timestamp(row.get("started_at"))
        ended = parse_timestamp(row.get("ended_at"))
        executed = parse_timestamp(row.get("executed_at"))
        effective_end = ended or executed
        time_source = "ended_at" if ended else "executed_at"
        attribution = self._describe_attribution(
            started, effective_end, period_start, period_end, time_source)

        # 老数据只有 executed_at 时，在原因里保留“取数用的是旧字段”的可核对信息。
        if started is None and effective_end is not None:
            attribution["attribution_reason"] += (
                f"（归属依据字段：{time_source}，原始时间 "
                f"{format_timestamp(effective_end)}，未臆造开始时间）"
            )

        return {
            "query_log_id": row["id"],
            "id": row["id"],
            "executor": row.get("executor"),
            "dataset": row.get("dataset"),
            "query_summary": row.get("query_summary"),
            "row_count": row.get("row_count"),
            "execution_time_ms": row.get("execution_time_ms"),
            "status": row.get("status"),
            "started_at": format_timestamp(started) or None,
            "ended_at": format_timestamp(ended) or None,
            "executed_at": format_timestamp(executed) or None,
            "registered_at": format_timestamp(parse_timestamp(row.get("registered_at"))) or None,
            "effective_time": attribution["effective_time"],
            "attribution_basis": attribution["attribution_basis"],
            "attribution_reason": attribution["attribution_reason"],
            "in_period": attribution["in_period"],
        }

    def _period_queries(
        self, period_start: datetime, period_end: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """返回本时段内的全部查询明细（按结束时间升序）与全部候选明细。"""
        rows = db.fetchall("SELECT * FROM query_log ORDER BY id")
        candidates = [
            self._query_detail(row, period_start, period_end) for row in rows
        ]
        included = [item for item in candidates if item["in_period"]]
        included.sort(key=lambda item: (item["effective_time"] or "", item["query_log_id"]))
        return included, candidates

    # ================================================================
    # 时段统计
    # ================================================================

    def period_stats(
        self, hours: float | int | str | None = 1,
        *, period_start: Any = None, period_end: Any = None,
        anchor: str = PERIOD_ANCHOR, base_date: Any = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """按本次请求的时段统计查询性能，明细/平均值/计数共用同一批日志。"""
        start, end, actual_hours = resolve_period(
            hours, period_start=period_start, period_end=period_end,
            anchor=anchor, base_date=base_date, now=now,
        )
        included, candidates = self._period_queries(start, end)

        total = len(included)
        slow = [item for item in included if item["status"] in SLOW_STATUSES]
        timeout = [item for item in included if item["status"] == "超时终止"]
        normal = [item for item in included if item["status"] == "正常"]
        durations = [int(item["execution_time_ms"] or 0) for item in included]
        total_ms = sum(durations)
        avg_ms = round(total_ms / total, 2) if total else 0.0

        avg_scope = {
            "period_start": format_timestamp(start),
            "period_end": format_timestamp(end),
            "hours": actual_hours,
            "attribution_rule": "按查询结束时间落入 [时段起点, 时段终点)",
            "query_log_ids": [item["query_log_id"] for item in included],
            "query_count": total,
            "sum_execution_ms": total_ms,
            "avg_execution_ms": avg_ms,
            "formula": "AVG(execution_time_ms) over query_log ids " + json.dumps(
                [item["query_log_id"] for item in included]),
        }

        return {
            "ok": True,
            "hours": actual_hours,
            "period": {
                "start": format_timestamp(start),
                "end": format_timestamp(end),
                "hours": actual_hours,
                "anchor": anchor,
            },
            "total_queries": total,
            "normal": len(normal),
            "slow_queries": len(slow),
            "timeout_queries": len(timeout),
            "avg_execution_ms": avg_ms,
            "slow_rate": round(len(slow) / total, 4) if total else 0.0,
            "slow_query_ids": [item["query_log_id"] for item in slow],
            "slow_query_details": slow,
            "queries": included,
            "avg_scope": avg_scope,
            "excluded_queries": [
                item for item in candidates if not item["in_period"]
            ],
            "computed_at": format_timestamp(datetime.now()),
        }

    def performance_summary(
        self, hours: int | float = 24, *, period_start: Any = None,
        period_end: Any = None, anchor: str = PERIOD_ANCHOR,
    ) -> dict[str, Any]:
        """获取指定时段内的查询性能摘要（hours 会真实参与取数）。"""
        stats = self.period_stats(
            hours, period_start=period_start, period_end=period_end, anchor=anchor)
        return {
            "total_queries": stats["total_queries"],
            "normal": stats["normal"],
            "slow_queries": stats["slow_queries"],
            "timeout_queries": stats["timeout_queries"],
            "avg_execution_ms": stats["avg_execution_ms"],
            "slow_rate": stats["slow_rate"],
            "period": stats["period"],
            "avg_scope": stats["avg_scope"],
        }

    def top_slow_queries(
        self, limit: int = 10, *, hours: int | float | None = None,
        period_start: Any = None, period_end: Any = None,
        anchor: str = PERIOD_ANCHOR,
    ) -> list[dict[str, Any]]:
        """获取最慢的查询记录；给定时段时只在本时段内排序。"""
        if hours is None and period_start is None and period_end is None:
            return db.fetchall(
                "SELECT * FROM query_log WHERE status IN ('慢查询','超时终止') "
                "ORDER BY execution_time_ms DESC LIMIT ?",
                [limit],
            )
        stats = self.period_stats(
            hours if hours is not None else 1,
            period_start=period_start, period_end=period_end, anchor=anchor,
        )
        slow = sorted(
            stats["slow_query_details"],
            key=lambda item: int(item["execution_time_ms"] or 0),
            reverse=True,
        )
        return slow[:limit]

    # ================================================================
    # 值班报告（签发即冻结）
    # ================================================================

    def issue_duty_report(
        self, hours: float | int | str | None = 1,
        *, period_start: Any = None, period_end: Any = None,
        anchor: str = PERIOD_ANCHOR, base_date: Any = None,
        generated_by: str = "值班长",
    ) -> dict[str, Any]:
        """签发一份值班报告：冻结统计来源、慢查询明细和平均耗时范围。"""
        stats = self.period_stats(
            hours, period_start=period_start, period_end=period_end,
            anchor=anchor, base_date=base_date,
        )
        generated_at = format_timestamp(datetime.now())
        slow_ids = [item["query_log_id"] for item in stats["slow_query_details"]]
        all_ids = [item["query_log_id"] for item in stats["queries"]]

        summary_content = {
            "period": stats["period"],
            "total_queries": stats["total_queries"],
            "normal": stats["normal"],
            "slow_queries": stats["slow_queries"],
            "timeout_queries": stats["timeout_queries"],
            "avg_execution_ms": stats["avg_execution_ms"],
            "slow_rate": stats["slow_rate"],
            "slow_query_ids": slow_ids,
            "slow_query_details": stats["slow_query_details"],
            "avg_scope": stats["avg_scope"],
            "attribution_rule": "明细、平均值、计数按同一时段归属取数（按查询结束时间）",
            "source_computed_at": stats["computed_at"],
        }

        report_id = db.insert("duty_reports", {
            "period_start": stats["period"]["start"],
            "period_end": stats["period"]["end"],
            "hours": stats["period"]["hours"],
            "generated_at": generated_at,
            "generated_by": generated_by or "值班长",
            "summary_content": json.dumps(summary_content, ensure_ascii=False),
            "slow_query_ids": json.dumps(slow_ids),
            "query_log_ids": json.dumps(all_ids),
            "avg_scope": json.dumps(stats["avg_scope"], ensure_ascii=False),
            "status": "已签发",
        })

        return self.duty_report_detail(report_id) | {"ok": True}

    def _load_duty_report(self, report_id: int) -> dict[str, Any] | None:
        return db.fetchone("SELECT * FROM duty_reports WHERE id=?", [report_id])

    def duty_report_detail(self, report_id: int) -> dict[str, Any]:
        """读取已签发报告；只读冻结内容，不用当前日志重算。"""
        row = self._load_duty_report(report_id)
        if row is None:
            return {"ok": False, "message": f"值班报告 {report_id} 不存在"}

        summary = json.loads(row["summary_content"]) if isinstance(
            row["summary_content"], str) else row["summary_content"]
        slow_ids = json.loads(row["slow_query_ids"]) if isinstance(
            row["slow_query_ids"], str) else row["slow_query_ids"]
        query_ids = json.loads(row["query_log_ids"]) if isinstance(
            row["query_log_ids"], str) else row["query_log_ids"]
        avg_scope = json.loads(row["avg_scope"]) if isinstance(
            row["avg_scope"], str) else row["avg_scope"]

        generated_at = parse_timestamp(row["generated_at"])
        period_start = parse_timestamp(row["period_start"])
        period_end = parse_timestamp(row["period_end"])
        included_ids = set(query_ids)

        # 签发后才登记、但按时间会落在本时段的查询：解释为什么报告里没有它。
        late_queries: list[dict[str, Any]] = []
        for candidate in db.fetchall("SELECT * FROM query_log ORDER BY id"):
            if candidate["id"] in included_ids:
                continue
            detail = self._query_detail(candidate, period_start, period_end)
            if not detail["in_period"]:
                continue
            registered_at = parse_timestamp(candidate.get("registered_at"))
            if registered_at is None or generated_at is None:
                continue
            if registered_at < generated_at:
                # 签发前已在库却未被收录，属于口径异常，不当作“迟到登记”。
                continue
            detail["explanation"] = (
                f"该查询于 {format_timestamp(registered_at)} 登记，晚于报告签发时间 "
                f"{format_timestamp(generated_at)}；签发时日志尚未入库，"
                f"按冻结规则不纳入本报告，已签发报告不改写。"
            )
            late_queries.append(detail)

        dispatches = db.fetchall(
            "SELECT * FROM duty_dispatches WHERE report_id=? ORDER BY id", [report_id]
        )

        return {
            "ok": True,
            "report_id": row["id"],
            "id": row["id"],
            "status": row["status"],
            "generated_at": row["generated_at"],
            "generated_by": row["generated_by"],
            "immutable": True,
            "period": {
                "start": row["period_start"],
                "end": row["period_end"],
                "hours": row["hours"],
            },
            "summary": summary,
            "total_queries": summary.get("total_queries"),
            "slow_queries": summary.get("slow_queries"),
            "avg_execution_ms": summary.get("avg_execution_ms"),
            "slow_query_ids": slow_ids,
            "query_log_ids": query_ids,
            "slow_query_details": summary.get("slow_query_details", []),
            "avg_scope": avg_scope,
            "dispatches": dispatches,
            "late_queries_not_in_report": late_queries,
        }

    def list_duty_reports(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = db.fetchall(
            "SELECT * FROM duty_reports ORDER BY id DESC LIMIT ?", [limit])
        reports = []
        for row in rows:
            summary = json.loads(row["summary_content"]) if isinstance(
                row["summary_content"], str) else row["summary_content"]
            reports.append({
                "id": row["id"],
                "period_start": row["period_start"],
                "period_end": row["period_end"],
                "hours": row["hours"],
                "generated_at": row["generated_at"],
                "generated_by": row["generated_by"],
                "status": row["status"],
                "total_queries": summary.get("total_queries"),
                "slow_queries": summary.get("slow_queries"),
                "avg_execution_ms": summary.get("avg_execution_ms"),
                "slow_query_ids": json.loads(row["slow_query_ids"]) if isinstance(
                    row["slow_query_ids"], str) else row["slow_query_ids"],
            })
        return reports

    def dispatch_slow_query(
        self, report_id: int, query_log_id: int,
        assignee: str = "值班工程师", note: str | None = None,
    ) -> dict[str, Any]:
        """主管按报告中实际列出的慢查询编号派单。"""
        row = self._load_duty_report(report_id)
        if row is None:
            return {"ok": False, "message": f"值班报告 {report_id} 不存在"}

        slow_ids = json.loads(row["slow_query_ids"]) if isinstance(
            row["slow_query_ids"], str) else row["slow_query_ids"]
        if query_log_id not in slow_ids:
            detail = self.duty_report_detail(report_id)
            late_ids = {
                item["query_log_id"]
                for item in detail.get("late_queries_not_in_report", [])
            }
            if query_log_id in late_ids:
                return {
                    "ok": False,
                    "message": (
                        f"查询 {query_log_id} 在报告 {report_id} 签发后才登记，"
                        f"不在该报告冻结的慢查询明细中，需纳入下一份值班报告。"
                    ),
                }
            return {
                "ok": False,
                "message": (
                    f"查询 {query_log_id} 不在报告 {report_id} 的慢查询明细中；"
                    f"可派单编号：{slow_ids or '无'}"
                ),
            }

        existing = db.fetchone(
            "SELECT * FROM duty_dispatches WHERE report_id=? AND query_log_id=?",
            [report_id, query_log_id],
        )
        if existing:
            return {
                "ok": False,
                "message": f"查询 {query_log_id} 已在报告 {report_id} 中派单",
                "dispatch_id": existing["id"],
            }

        dispatch_id = db.insert("duty_dispatches", {
            "report_id": report_id,
            "query_log_id": query_log_id,
            "assignee": assignee or "值班工程师",
            "note": note or "",
            "status": "已派单",
            "created_at": format_timestamp(datetime.now()),
        })
        dispatch = db.fetchone(
            "SELECT * FROM duty_dispatches WHERE id=?", [dispatch_id])
        return {"ok": True, "message": f"已按报告 {report_id} 的慢查询 {query_log_id} 派单",
                "dispatch": dispatch}

    def explain_report_coverage(self, query_log_id: int) -> dict[str, Any]:
        """说明某条查询被哪些已签发报告收录、为何没被收录。"""
        query = db.fetchone("SELECT * FROM query_log WHERE id=?", [query_log_id])
        if query is None:
            return {"ok": False, "message": f"查询 {query_log_id} 不存在"}

        coverage = []
        for row in db.fetchall("SELECT * FROM duty_reports ORDER BY id"):
            ids = json.loads(row["query_log_ids"]) if isinstance(
                row["query_log_ids"], str) else row["query_log_ids"]
            slow_ids = json.loads(row["slow_query_ids"]) if isinstance(
                row["slow_query_ids"], str) else row["slow_query_ids"]
            coverage.append({
                "report_id": row["id"],
                "period_start": row["period_start"],
                "period_end": row["period_end"],
                "generated_at": row["generated_at"],
                "included": query_log_id in ids,
                "as_slow_query": query_log_id in slow_ids,
            })

        return {
            "ok": True,
            "query_log_id": query_log_id,
            "registered_at": query.get("registered_at"),
            "coverage": coverage,
        }

    # ================================================================
    # 兼容旧分析接口
    # ================================================================

    def dataset_usage(self) -> list[dict[str, Any]]:
        """统计各数据集的查询频率。"""
        return db.fetchall(
            "SELECT dataset, COUNT(*) as total_queries, AVG(execution_time_ms) as avg_ms "
            "FROM query_log GROUP BY dataset ORDER BY total_queries DESC",
        )

    def domain_snapshot(self) -> dict[str, Any]:
        snapshot = super().domain_snapshot()
        snapshot["total_queries"] = db.count("query_log")
        snapshot["slow_count"] = db.count("query_log", "status='慢查询'")
        snapshot["timeout_count"] = db.count("query_log", "status='超时终止'")
        return snapshot
