import { sourceType, recordTime, timeValue } from './catalog.js'

export const sourceForms = ['PDF', '图片', '文本', '结构化数据', '混合', '未识别']
export const sortOptions = [
    { value: 'recent', label: '最近更新' },
    { value: 'oldest', label: '最早更新' },
    { value: 'name', label: '名称 A–Z' }
]
export function defaultFilters() {
    return { search: '', sourceForm: '', modality: '', trainingType: '', release: '', samples: '', sort: 'recent' }
}

export function filterFields(mode) {
    return mode === 'materials' ? [
        { key: 'sourceForm', label: '数据形式', options: [{ value: '', label: '全部形式' }, ...sourceForms.map(value => ({ value, label: value }))] }
    ] : [
        { key: 'modality', label: '模态', options: [{ value: '', label: '全部模态' }, { value: 'text', label: '文本' }, { value: 'image_text', label: '图文' }] },
        { key: 'trainingType', label: '训练类型', options: [{ value: '', label: '全部训练类型' }, { value: 'sft', label: 'SFT' }, { value: 'dpo', label: 'DPO' }] },
        { key: 'release', label: '发布情况', options: [{ value: '', label: '全部发布情况' }, { value: 'published', label: '有发布版本' }, { value: 'unpublished', label: '无发布版本' }] },
        { key: 'samples', label: '样本情况', options: [{ value: '', label: '全部样本情况' }, { value: 'nonempty', label: '有样本' }, { value: 'empty', label: '空数据集' }] }
    ]
}

export function activeFilters(filters, mode) {
    const active = []
    if (filters.search.trim()) active.push({ key: 'search', label: `名称：${filters.search.trim()}` })
    for (const field of filterFields(mode)) {
        const option = field.options.find(option => option.value && option.value === filters[field.key])
        if (option) active.push({ key: field.key, label: `${field.label}：${option.label}` })
    }
    return active
}

export function filterCatalog(records, filters, mode) {
    const query = filters.search.trim().toLocaleLowerCase()
    const rows = records.filter(record => {
        if (query && !String(record.name || '').toLocaleLowerCase().includes(query)) return false
        if (mode === 'materials') return !filters.sourceForm || sourceType(record) === filters.sourceForm
        if (filters.modality && record.modality !== filters.modality) return false
        if (filters.trainingType && (record.training_type || 'sft').toLowerCase() !== filters.trainingType) return false
        const published = Number(record.latest_release_version) > 0
        if (filters.release === 'published' && !published || filters.release === 'unpublished' && published) return false
        const count = Number(record.row_count) || 0
        if (filters.samples === 'empty' && count > 0 || filters.samples === 'nonempty' && count <= 0) return false
        return true
    })
    const byName = (a, b) => String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN', { numeric: true })
    return rows.sort((a, b) => {
        if (filters.sort === 'name') return byName(a, b)
        if (filters.sort === 'samples' && mode !== 'materials') return (Number(b.row_count) || 0) - (Number(a.row_count) || 0) || byName(a, b)
        const at = timeValue(recordTime(a)), bt = timeValue(recordTime(b))
        // Unknown dates always go last, including oldest-first ordering.
        if (!at || !bt) return (bt ? 1 : 0) - (at ? 1 : 0) || byName(a, b)
        return (filters.sort === 'oldest' ? at - bt : bt - at) || byName(a, b)
    })
}
