import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export type SlowQueryDetail = {
  query_log_id: number
  id: number
  executor: string
  dataset: string
  query_summary: string
  row_count: number
  execution_time_ms: number
  status: string
  started_at: string | null
  ended_at: string | null
  executed_at: string | null
  registered_at: string | null
  effective_time: string | null
  attribution_basis: string | null
  attribution_reason: string
  in_period: boolean
}

export type PeriodStats = {
  ok: boolean
  hours: number
  period: { start: string; end: string; hours: number; anchor: string }
  total_queries: number
  normal: number
  slow_queries: number
  timeout_queries: number
  avg_execution_ms: number
  slow_rate: number
  slow_query_ids: number[]
  slow_query_details: SlowQueryDetail[]
  queries: SlowQueryDetail[]
  avg_scope: {
    period_start: string
    period_end: string
    hours: number
    query_log_ids: number[]
    query_count: number
    sum_execution_ms: number
    avg_execution_ms: number
    attribution_rule: string
    formula: string
  }
  excluded_queries: SlowQueryDetail[]
  computed_at: string
}

export type PeriodParams = {
  hours: number
  anchor?: string
  period_start?: string
  period_end?: string
  base_date?: string
}

export type DutyReportSummary = {
  id: number
  period_start: string
  period_end: string
  hours: number
  generated_at: string
  generated_by: string
  status: string
  total_queries: number
  slow_queries: number
  avg_execution_ms: number
  slow_query_ids: number[]
}

export type DutyReportDetail = DutyReportSummary & {
  report_id: number
  immutable: boolean
  summary: Record<string, unknown> & {
    slow_query_details?: SlowQueryDetail[]
  }
  slow_query_details: SlowQueryDetail[]
  query_log_ids: number[]
  avg_scope: PeriodStats['avg_scope']
  dispatches: {
    id: number
    query_log_id: number
    assignee: string
    note: string
    status: string
    created_at: string
  }[]
  late_queries_not_in_report: (SlowQueryDetail & { explanation: string })[]
}

export async function loadPeriodStats(params: PeriodParams): Promise<PeriodStats> {
  const response = await request('/api/query_history/period-stats', {
    method: 'POST',
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? '时段统计读取失败')
  }
  return await response.json()
}

export async function issueDutyReport(params: PeriodParams): Promise<DutyReportDetail> {
  const response = await request('/api/query_history/period-stats/issue-report', {
    method: 'POST',
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? '值班报告签发失败')
  }
  return await response.json()
}

export async function loadDutyReports(): Promise<{ items: DutyReportSummary[]; total: number }> {
  const response = await request('/api/query_history/period-stats/reports')
  if (!response.ok) throw new Error('值班报告列表读取失败')
  return await response.json()
}

export async function loadDutyReport(reportId: number): Promise<DutyReportDetail> {
  const response = await request(`/api/query_history/period-stats/reports/${reportId}`)
  if (!response.ok) throw new Error('值班报告详情读取失败')
  return await response.json()
}

export async function dispatchSlowQuery(
  reportId: number,
  queryLogId: number,
  assignee: string,
  note = '',
): Promise<{ ok: boolean; message: string }> {
  const response = await request(
    `/api/query_history/period-stats/reports/${reportId}/dispatch`,
    {
      method: 'POST',
      body: JSON.stringify({ query_log_id: queryLogId, assignee, note }),
    },
  )
  return await response.json()
}

export type QueryLogInput = {
  executor: string
  dataset: string
  query_summary: string
  row_count?: number
  execution_time_ms: number
  started_at?: string | null
  ended_at?: string | null
}

export async function registerQueryLog(
  payload: QueryLogInput,
): Promise<{ ok: boolean; id: number; status: string }> {
  const response = await request('/api/query_history/logs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error('查询补登失败')
  return await response.json()
}
