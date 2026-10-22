// Only flag conditions supported by canvas metadata; the server remains authoritative.
export function checkPipeline(nodes, edges, source) {
    const issues = [], operators = nodes.filter(node => node.type === 'operator-node')
    const add = (node, message, kind = 'parameter') => issues.push({ nodeId: node?.id, name: node?.data?.label || node?.data?.name || 'Pipeline', message, kind })
    if (!source || !nodes.some(node => node.type === 'database-node')) add(null, '请选择输入数据集。', 'input')
    if (!operators.length) add(null, '请至少添加一个算子。', 'operator')
    const validEdges = edges.filter(edge => nodes.some(node => node.id === edge.source) && nodes.some(node => node.id === edge.target))
    const reachable = new Set(nodes.filter(node => node.type === 'database-node').map(node => node.id))
    let changed = true
    while (changed) { changed = false; for (const edge of validEdges) if (reachable.has(edge.source) && !reachable.has(edge.target)) { reachable.add(edge.target); changed = true } }
    const incoming = new Map(nodes.map(node => [node.id, new Set(validEdges.filter(edge => edge.target === node.id).map(edge => edge.source))]))
    const removed = new Set()
    while (true) { const ready = [...incoming].filter(([id, parents]) => !removed.has(id) && [...parents].every(parent => removed.has(parent))); if (!ready.length) break; ready.forEach(([id]) => removed.add(id)) }
    if (removed.size < nodes.length) add(null, '流程中存在循环连接，请调整为单向执行顺序。', 'graph')
    for (const node of operators) {
        if (source && !reachable.has(node.id)) add(node, '未连接到输入数据，请连接前序节点。', 'graph')
        if (node.data.parameterLoading || node.data.parameterError || !node.data.operatorParams) { add(node, node.data.parameterError || '参数尚未加载完成，请打开参数详情后重试。'); continue }
        for (const [section, params] of Object.entries(node.data.operatorParams)) for (const param of params || []) {
            if (['self', 'storage', 'args', 'kwargs'].includes(param.name) || ['VAR_POSITIONAL','VAR_KEYWORD'].includes(param.kind)) continue
            const empty = param.value == null || typeof param.value === 'string' && !param.value.trim() || (param.name === 'prompt_template' && typeof param.value === 'object' && !param.value?.ref && !param.value?.cls_name)
            if (/^(llm|embedding)_serving$/.test(param.name) && empty && param.required !== false) add(node, '尚未配置模型服务。', 'serving')
            else if (section === 'run' && /^input_.*key(s)?$/.test(param.name) && empty && param.default_value != null) add(node, `请填写输入字段 ${param.name}。`)
            else if (param.required === true && empty) add(node, `请填写必填参数 ${param.name}。`)
        }
    }
    return issues
}
