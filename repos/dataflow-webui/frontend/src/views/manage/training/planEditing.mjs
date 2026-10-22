// Validate editor structure before applying it to reactive form controls.
export function parseAdvancedPlan(text, defaults) {
    const input = JSON.parse(text)
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw Error('需要 JSON 对象')
    const plan = { ...defaults, ...input }
    const object = (value) => value && typeof value === 'object' && !Array.isArray(value)
    if (
        !object(plan.strategy) ||
        typeof plan.strategy.family !== 'string' ||
        !object(plan.strategy.params)
    ) {
        throw Error('strategy 需要 family 字符串和 params 对象')
    }
    if (!Array.isArray(plan.data) || !plan.data.every(object))
        throw Error('data 需要数据绑定对象列表')
    const stages = plan.strategy.params.stages
    if (
        plan.strategy.family === 'lego' &&
        stages !== undefined &&
        (!Array.isArray(stages) || !stages.every(object))
    ) {
        throw Error('Lego stages 需要阶段对象列表')
    }
    return plan
}
