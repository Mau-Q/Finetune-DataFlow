export const terminalStatuses = new Set(['completed', 'failed', 'cancelled'])
export function statusLabel(status) {
    return ({ pending: '排队中', queued: '排队中', initializing: '初始化中', initialized: '就绪', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消', waiting: '等待', skipped: '未执行', unknown: '未报告' })[status] || '等待状态'
}
export function executionProgress(execution = {}) {
    const details = execution.operators_detail || {}
    const config = execution.pipeline_config?.operators || []
    const reported = Object.entries(details).map(([key, item]) => ({ ...item, key }))
    const steps = (config.length ? config.map((op, index) => {
        const info = reported.find(step => step.index === index && step.name === op.name)
        return info || { key: `${op.name}_${index}`, name: op.name, index, status: terminalStatuses.has(execution.status) ? (execution.status === 'completed' ? 'unknown' : 'skipped') : 'waiting' }
    }) : reported).sort((a, b) => a.index - b.index).map(step => ({
        ...step,
        percentage: step.status === 'running' && typeof step.progress_percentage === 'number' && Number.isFinite(step.progress_percentage) ? Math.min(100, Math.max(0, step.progress_percentage)) : null
    }))
    const active = steps.find(step => step.status === 'running') || steps.find(step => step.status === 'initializing')
    const failed = steps.find(step => step.status === 'failed')
    const logs = execution.logs || []
    return { steps, active, completed: steps.filter(step => step.status === 'completed').length, total: steps.length,
        error: failed?.error || (execution.status === 'failed' ? logs.at(-1) || '任务执行失败，请展开日志查看原因。' : ''),
        terminal: terminalStatuses.has(execution.status), label: statusLabel(execution.status) }
}
export function elapsedLabel(start, end, now = Date.now()) {
    if (!start) return '尚未开始'
    const from = Date.parse(start), to = end ? Date.parse(end) : now
    if (!Number.isFinite(from) || !Number.isFinite(to)) return '用时未知'
    const seconds = Math.max(0, Math.floor((to - from) / 1000))
    const hours = Math.floor(seconds / 3600)
    return `${hours ? hours + ':' : ''}${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}
