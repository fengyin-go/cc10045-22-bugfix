"""业务路由汇总：资源路由 + 管道路由 + 查询历史时段统计/值班报告路由。"""
from __future__ import annotations

from app.routers import resource
from app.routers import pipeline
from app.routers import query_duty

ROUTERS = [resource]
PIPELINE_ROUTER = pipeline.router
# 专用路由必须先于通用资源路由注册，否则 /api/query_history/period-stats
# 会被 /api/{module}/{entry_id} 当作 entry_id 解析。
QUERY_DUTY_ROUTER = query_duty.router