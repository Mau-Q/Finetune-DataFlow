export const canonicalStatus = status => ({success:'completed',pending:'queued'}[status] || status)
export function durationMs(task){
    const start=task.started_at, end=task.completed_at || task.finished_at || task.ended_at
    if(!start || !end)return null
    const duration=new Date(end)-new Date(start)
    return Number.isFinite(duration) && duration>=0 ? duration : null
}
export function averageDuration(tasks){
    const times=tasks.map(durationMs).filter(value=>value!==null)
    if(!times.length)return '暂无数据'
    const value=Math.round(times.reduce((sum,v)=>sum+v,0)/times.length)
    return value<1000?`${value}ms`:`${(value/1000).toFixed(2)}s`
}
export function terminalSuccessRate(stats){
    const completed=Number(stats.completed ?? stats.success) || 0
    const total=completed+(Number(stats.failed)||0)+(Number(stats.cancelled)||0)
    return total ? Math.round(completed/total*100) : 0
}
export const statusLabel = status => ({completed:'已完成',running:'运行中',queued:'排队中',failed:'失败',cancelled:'已取消'}[canonicalStatus(status)] || status || '未知')
