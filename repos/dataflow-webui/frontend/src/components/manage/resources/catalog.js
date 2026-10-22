export function matchesSource(resource, source) {
    return source === 'user'
        ? resource.source === 'user' || resource.personal === true
        : resource.source === 'builtin'
}
export function usageCount(resource) {
    return new Set(
        resource.references
            .filter((ref) => ref.pipeline_source === 'user')
            .map((ref) => ref.pipeline_id)
    ).size
}
export function usageKind(kind) {
    return (
        { explicit: '显式引用', operator_default: '算子默认', operator_fixed: '算子固定' }[kind] ||
        '显式引用'
    )
}
export function pipelineOptions(pipelines, source) {
    if (source === 'builtin') return pipelines.filter((p) => p.origin === 'preset')
    return [
        { id: 'family:text-sft', name: '文本 SFT', family: 'text-sft' },
        { id: 'family:image-sft', name: '图像 SFT', family: 'image-sft' }
    ].map((group) => {
        const members = pipelines.filter((p) => p.source === 'user' && p.family === group.family)
        return {
            ...group,
            member_ids: members.map((p) => p.id),
            operators: [...new Set(members.flatMap((p) => p.operators || []))],
            schema_operators: [...new Set(members.flatMap((p) => p.schema_operators || []))]
        }
    })
}
export function matchesPipeline(reference, pipeline, options) {
    if (!pipeline) return true
    const selected = options.find((p) => p.id === pipeline)
    return (
        reference.pipeline_id === pipeline ||
        !!selected?.member_ids?.includes(reference.pipeline_id)
    )
}
export const usages = ['通用', '文本 SFT', '图文 SFT', '文本 DPO', '图文 DPO']
export function filterResources(
    records,
    {
        source = 'user',
        search = '',
        usage = '',
        purpose = '',
        pipeline = '',
        relation = 'referenced',
        operator = ''
    },
    pipelines = []
) {
    const q = search.trim().toLowerCase()
    const selected = pipelines.find((p) => p.id === pipeline)
    return records.filter(
        (r) =>
            matchesSource(r, source) &&
            (!q ||
                [r.name, r.id, r.description, ...(r.operators || []), ...(r.variables || [])]
                    .join(' ')
                    .toLowerCase()
                    .includes(q)) &&
            (!usage || r.usages.includes(usage)) &&
            (!purpose || r.purpose === purpose) &&
            (!operator || r.operators.includes(operator)) &&
            (!pipeline ||
                (relation === 'referenced'
                    ? r.references.some((ref) => matchesPipeline(ref, pipeline, pipelines))
                    : !!selected &&
                      (r.resource_kind === 'schema'
                          ? selected.schema_operators?.length > 0
                          : r.operators.some((op) => selected.operators.includes(op)))))
    )
}
export function timeLabel(value) {
    return value && Number.isFinite(new Date(value).getTime())
        ? new Date(value).toLocaleString('zh-CN', { hour12: false })
        : '未记录'
}
export function variablesOf(text) {
    const names = []
    for (const match of (text || '').matchAll(/\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}/g))
        if (match[1] && !names.includes(match[1])) names.push(match[1])
    return names
}
