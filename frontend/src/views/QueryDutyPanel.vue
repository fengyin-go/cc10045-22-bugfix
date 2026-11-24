<template>
  <section class="period-panel" data-testid="period-panel">
    <header class="period-head">
      <div>
        <h3>时段统计</h3>
        <p class="period-desc">
          时段从 {{ anchor }} 起算；明细、平均值、计数按本次请求的同一时段归属取数，
          跨过时段起点的查询按结束时间归入本时段。
        </p>
      </div>
      <div class="period-form">
        <label>
          <span>统计小时数</span>
          <input
            v-model.number="hours"
            type="number"
            min="0.25"
            step="0.25"
            data-testid="period-hours"
          />
        </label>
        <label>
          <span>时段起点</span>
          <input v-model="anchor" type="time" data-testid="period-anchor" />
        </label>
        <label>
          <span>基准日期（可选）</span>
          <input v-model="baseDate" type="date" data-testid="period-base-date" />
        </label>
        <button class="btn primary" data-testid="run-period-stats" type="button" @click="runStats">
          统计时段
        </button>
        <button class="btn" data-testid="issue-duty-report" type="button" @click="issueReport">
          按此时段发值班报告
        </button>
      </div>
    </header>

    <p v-if="panelError" class="error-text" data-testid="period-error">{{ panelError }}</p>
    <p v-if="panelNotice" class="period-notice" data-testid="period-notice">{{ panelNotice }}</p>

    <template v-if="stats">
      <div class="stat-row" data-testid="period-summary">
        <article class="stat-card">
          <span class="stat-label">时段范围</span>
          <strong class="stat-value small" data-testid="period-range">
            {{ stats.period.start }} ~ {{ stats.period.end }}
          </strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">时段内查询数</span>
          <strong class="stat-value" data-testid="period-total">{{ stats.total_queries }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">时段内慢查询数</span>
          <strong class="stat-value" data-testid="period-slow">{{ stats.slow_queries }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">平均耗时(ms)</span>
          <strong class="stat-value" data-testid="period-avg">{{ stats.avg_execution_ms }}</strong>
        </article>
      </div>

      <div class="period-block" data-testid="period-avg-scope">
        <h4>平均耗时采用的日志范围</h4>
        <p>
          口径：{{ stats.avg_scope.attribution_rule }}；共
          <strong>{{ stats.avg_scope.query_count }}</strong> 条，日志编号
          <code data-testid="period-avg-ids">{{ stats.avg_scope.query_log_ids.join(', ') || '无' }}</code>；
          合计 {{ stats.avg_scope.sum_execution_ms }}ms / {{ stats.avg_scope.query_count }} =
          {{ stats.avg_scope.avg_execution_ms }}ms。
        </p>
      </div>

      <div class="period-block">
        <h4>本时段慢查询明细（可按编号核对）</h4>
        <table class="data-table" data-testid="period-slow-table">
          <thead>
            <tr>
              <th>慢查询编号</th>
              <th>耗时(ms)</th>
              <th>状态</th>
              <th>涉及数据集</th>
              <th>开始时间</th>
              <th>结束时间</th>
              <th>归属依据</th>
              <th>归属原因</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in stats.slow_query_details"
              :key="item.query_log_id"
              :data-testid="`slow-detail-${item.query_log_id}`"
            >
              <td>#{{ item.query_log_id }}</td>
              <td>{{ item.execution_time_ms }}</td>
              <td>{{ item.status }}</td>
              <td>{{ item.dataset }}</td>
              <td>{{ item.started_at ?? '—' }}</td>
              <td>{{ item.ended_at ?? item.executed_at ?? '—' }}</td>
              <td>{{ item.attribution_basis ?? '—' }}</td>
              <td>{{ item.attribution_reason }}</td>
            </tr>
            <tr v-if="!stats.slow_query_details.length">
              <td colspan="8" class="empty-state">本时段没有慢查询</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="period-block">
        <h4>不属于本时段的查询（不参与本次统计）</h4>
        <table class="data-table" data-testid="period-excluded-table">
          <thead>
            <tr><th>编号</th><th>耗时(ms)</th><th>状态</th><th>结束时间</th><th>未纳入原因</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="item in stats.excluded_queries"
              :key="item.query_log_id"
              :data-testid="`excluded-${item.query_log_id}`"
            >
              <td>#{{ item.query_log_id }}</td>
              <td>{{ item.execution_time_ms }}</td>
              <td>{{ item.status }}</td>
              <td>{{ item.effective_time ?? '—' }}</td>
              <td>{{ item.attribution_reason }}</td>
            </tr>
            <tr v-if="!stats.excluded_queries.length">
              <td colspan="5" class="empty-state">没有时段外查询</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <div class="period-block">
      <header class="period-block-head">
        <h4>值班报告</h4>
        <div class="period-form">
          <button class="btn ghost" data-testid="reload-duty-reports" type="button" @click="loadReports">
            刷新报告列表
          </button>
          <button class="btn" data-testid="open-late-log" type="button" @click="showLateLog = !showLateLog">
            补登迟到查询
          </button>
        </div>
      </header>

      <form v-if="showLateLog" class="period-form" data-testid="late-log-form" @submit.prevent="registerLateLog">
        <label><span>执行人</span><input v-model="lateLog.executor" data-testid="late-executor" /></label>
        <label><span>涉及数据集</span><input v-model="lateLog.dataset" data-testid="late-dataset" /></label>
        <label><span>查询摘要</span><input v-model="lateLog.query_summary" data-testid="late-summary" /></label>
        <label><span>耗时(ms)</span><input v-model.number="lateLog.execution_time_ms" type="number" data-testid="late-duration" /></label>
        <label><span>开始时间</span><input v-model="lateLog.started_at" type="datetime-local" step="1" data-testid="late-start" /></label>
        <label><span>结束时间</span><input v-model="lateLog.ended_at" type="datetime-local" step="1" data-testid="late-end" /></label>
        <button class="btn primary" data-testid="submit-late-log" type="submit">登记</button>
      </form>

      <table class="data-table" data-testid="duty-report-list">
        <thead>
          <tr>
            <th>报告编号</th><th>时段</th><th>签发时间</th><th>查询数</th><th>慢查询编号</th>
            <th>平均耗时(ms)</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="report in reports" :key="report.id" :data-testid="`duty-report-${report.id}`">
            <td>#{{ report.id }}</td>
            <td>{{ report.period_start }} ~ {{ report.period_end }}</td>
            <td>{{ report.generated_at }}</td>
            <td>{{ report.total_queries }}</td>
            <td>{{ report.slow_query_ids.join(', ') || '无' }}</td>
            <td>{{ report.avg_execution_ms }}</td>
            <td>
              <button class="link" data-testid="open-duty-report" type="button" @click="openReport(report.id)">
                查看详情
              </button>
            </td>
          </tr>
          <tr v-if="!reports.length">
            <td colspan="7" class="empty-state">暂无已签发值班报告</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="activeReport" class="modal-backdrop" data-testid="duty-report-detail">
      <section class="modal wide">
        <header class="period-block-head">
          <h3>值班报告 #{{ activeReport.report_id }} 详情</h3>
          <button class="btn ghost" data-testid="close-duty-report" type="button" @click="activeReport = null">
            关闭
          </button>
        </header>
        <p class="period-desc">
          已签发报告为只读冻结内容：签发后补登或重算不会改写本报告。
        </p>

        <div class="stat-row">
          <article class="stat-card">
            <span class="stat-label">时段</span>
            <strong class="stat-value small">{{ activeReport.period_start }} ~ {{ activeReport.period_end }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">查询数 / 慢查询</span>
            <strong class="stat-value">{{ activeReport.total_queries }} / {{ activeReport.slow_queries }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">平均耗时(ms)</span>
            <strong class="stat-value" data-testid="report-avg">{{ activeReport.avg_execution_ms }}</strong>
          </article>
        </div>

        <div class="period-block">
          <h4>关联的慢查询明细</h4>
          <table class="data-table" data-testid="report-slow-table">
            <thead>
              <tr>
                <th>慢查询编号</th><th>耗时(ms)</th><th>开始时间</th><th>结束时间</th>
                <th>归属依据</th><th>归属原因</th><th>派单</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in activeReport.slow_query_details"
                :key="item.query_log_id"
                :data-testid="`report-slow-${item.query_log_id}`"
              >
                <td>#{{ item.query_log_id }}</td>
                <td>{{ item.execution_time_ms }}</td>
                <td>{{ item.started_at ?? '—' }}</td>
                <td>{{ item.ended_at ?? item.executed_at ?? '—' }}</td>
                <td>{{ item.attribution_basis ?? '—' }}</td>
                <td>{{ item.attribution_reason }}</td>
                <td>
                  <input
                    v-model="dispatchAssignee[item.query_log_id]"
                    :data-testid="`dispatch-assignee-${item.query_log_id}`"
                    placeholder="派单人"
                  />
                  <button
                    class="link"
                    :data-testid="`dispatch-${item.query_log_id}`"
                    type="button"
                    @click="dispatch(item.query_log_id)"
                  >
                    派单
                  </button>
                </td>
              </tr>
              <tr v-if="!activeReport.slow_query_details.length">
                <td colspan="7" class="empty-state">本报告没有慢查询</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="period-block" data-testid="report-avg-scope">
          <h4>平均耗时采用的日志范围</h4>
          <p>
            {{ activeReport.avg_scope.attribution_rule }}；报告平均耗时
            {{ activeReport.avg_scope.avg_execution_ms }}ms，共
            {{ activeReport.avg_scope.query_count }} 条，日志编号
            <code>{{ activeReport.avg_scope.query_log_ids.join(', ') || '无' }}</code>。
          </p>
        </div>

        <div v-if="activeReport.late_queries_not_in_report.length" class="period-block" data-testid="report-late-queries">
          <h4>签发后补登、按本时段应纳入但未纳入的查询</h4>
          <table class="data-table">
            <thead>
              <tr><th>编号</th><th>耗时(ms)</th><th>结束时间</th><th>说明</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="item in activeReport.late_queries_not_in_report"
                :key="item.query_log_id"
                :data-testid="`report-late-${item.query_log_id}`"
              >
                <td>#{{ item.query_log_id }}</td>
                <td>{{ item.execution_time_ms }}</td>
                <td>{{ item.effective_time ?? '—' }}</td>
                <td>{{ item.explanation }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="activeReport.dispatches.length" class="period-block" data-testid="report-dispatches">
          <h4>已派单</h4>
          <ul>
            <li v-for="item in activeReport.dispatches" :key="item.id">
              慢查询 #{{ item.query_log_id }} → {{ item.assignee }}（{{ item.status }}，{{ item.created_at }}）
            </li>
          </ul>
        </div>

        <p v-if="dispatchMessage" class="period-notice" data-testid="dispatch-message">{{ dispatchMessage }}</p>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  dispatchSlowQuery,
  issueDutyReport,
  loadDutyReport,
  loadDutyReports,
  loadPeriodStats,
  registerQueryLog,
} from '@/api/backend-service'
import type { DutyReportDetail, DutyReportSummary, PeriodParams, PeriodStats } from '@/api/backend-service'

const hours = ref(1)
const anchor = ref('09:00')
const baseDate = ref('')
const stats = ref<PeriodStats | null>(null)
const reports = ref<DutyReportSummary[]>([])
const activeReport = ref<DutyReportDetail | null>(null)
const panelError = ref('')
const panelNotice = ref('')
const dispatchMessage = ref('')
const dispatchAssignee = reactive<Record<number, string>>({})
const showLateLog = ref(false)
const lateLog = reactive({
  executor: '分析员',
  dataset: 'events',
  query_summary: '',
  execution_time_ms: 900,
  started_at: '',
  ended_at: '',
})

function buildParams(): PeriodParams {
  const params: PeriodParams = { hours: Number(hours.value) || 1, anchor: anchor.value || '09:00' }
  if (baseDate.value) params.base_date = baseDate.value
  return params
}

async function runStats() {
  panelError.value = ''
  panelNotice.value = ''
  try {
    stats.value = await loadPeriodStats(buildParams())
  } catch (error) {
    panelError.value = error instanceof Error ? error.message : '时段统计失败'
  }
}

async function issueReport() {
  panelError.value = ''
  panelNotice.value = ''
  try {
    const report = await issueDutyReport(buildParams())
    panelNotice.value = `已签发值班报告 #${report.report_id}，慢查询编号 ${report.slow_query_ids.join(', ') || '无'}`
    await loadReports()
    await openReport(report.report_id)
  } catch (error) {
    panelError.value = error instanceof Error ? error.message : '值班报告签发失败'
  }
}

async function loadReports() {
  try {
    const payload = await loadDutyReports()
    reports.value = payload.items
  } catch (error) {
    panelError.value = error instanceof Error ? error.message : '值班报告列表读取失败'
  }
}

async function openReport(reportId: number) {
  dispatchMessage.value = ''
  try {
    activeReport.value = await loadDutyReport(reportId)
  } catch (error) {
    panelError.value = error instanceof Error ? error.message : '值班报告详情读取失败'
  }
}

async function dispatch(queryLogId: number) {
  if (!activeReport.value) return
  dispatchMessage.value = ''
  try {
    const result = await dispatchSlowQuery(
      activeReport.value.report_id,
      queryLogId,
      dispatchAssignee[queryLogId] || '值班工程师',
    )
    dispatchMessage.value = result.message
    if (result.ok) {
      activeReport.value = await loadDutyReport(activeReport.value.report_id)
    }
  } catch (error) {
    dispatchMessage.value = error instanceof Error ? error.message : '派单失败'
  }
}

async function registerLateLog() {
  panelError.value = ''
  panelNotice.value = ''
  try {
    const payload = await registerQueryLog({
      executor: lateLog.executor,
      dataset: lateLog.dataset,
      query_summary: lateLog.query_summary,
      execution_time_ms: lateLog.execution_time_ms,
      started_at: lateLog.started_at || null,
      ended_at: lateLog.ended_at || null,
    })
    panelNotice.value = `查询 #${payload.id} 已补登（${payload.status}）；已签发报告不会被改写。`
    showLateLog.value = false
    await loadReports()
    if (activeReport.value) await openReport(activeReport.value.report_id)
  } catch (error) {
    panelError.value = error instanceof Error ? error.message : '补登失败'
  }
}

onMounted(async () => {
  await loadReports()
  await runStats()
})
</script>
