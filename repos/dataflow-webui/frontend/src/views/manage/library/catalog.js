// Catalog presentation only: storage formats and training contracts remain separate.
export function sourceType(item) {
    const content = { pdf: 'PDF', image: '图片', pdf_image: '混合', mixed: '混合', text: '文本', structured: '结构化数据' }[item.content_type]
    if (content) return content
    const type = (item.type || '').toLowerCase()
    if (type === 'pdf') return 'PDF'
    if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'].includes(type)) return '图片'
    if (['txt', 'md', 'text', 'log'].includes(type)) return '文本'
    if (['json', 'jsonl', 'csv', 'parquet', 'excel', 'xlsx', 'xls', 'pickle'].includes(type)) return '结构化数据'
    return '未识别'
}
export function sourceCount(item) {
    const kind = sourceType(item)
    if (item.file_count != null) return `${item.file_count.toLocaleString('zh-CN')} ${kind === '图片' ? '张图片' : '个文件'}`
    if (['PDF', '图片', '文本'].includes(kind)) return kind === '图片' ? '1 张图片' : '1 个文件'
    return `${(item.num_samples || 0).toLocaleString('zh-CN')} 条记录`
}
export function recordTime(item) { return item.updated_at || item.created_at || item.added_at || '' }
export function timeValue(value) { const n = value ? new Date(value).getTime() : NaN; return Number.isFinite(n) ? n : 0 }
export function recentFirst(records) { return [...records].sort((a, b) => timeValue(recordTime(b)) - timeValue(recordTime(a))) }
export function formatTime(value, seconds = false) {
    if (!value || !Number.isFinite(new Date(value).getTime())) return '未记录'
    const d = new Date(value), pad = n => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}${seconds ? `:${pad(d.getSeconds())}` : ''}`
}
export function releaseLabel(item) { return item.latest_release_version ? `v${item.latest_release_version}` : '未发布' }

export function scanFolder(files) {
    const accepted = [], skipped = [], kinds = new Set()
    const supported = /\.(pdf|png|jpe?g|webp|gif|bmp|txt|md|json|jsonl|csv|parquet)$/i
    for (const file of files) {
        const path = (file.webkitRelativePath || file.name).replace(/\\/g, '/')
        if (path.split('/').some(p => p.startsWith('.') || p === '__MACOSX') || !supported.test(path)) { skipped.push(path); continue }
        accepted.push(file)
        kinds.add(sourceType({ type: path.split('.').pop() }))
    }
    return { accepted, skipped, type: kinds.size > 1 ? '混合' : [...kinds][0] || '未识别' }
}

export async function droppedSelection(items) {
    // Capture entry handles synchronously before the drop event releases its data.
    const entries = [...items].map(item => ({ entry: item.webkitGetAsEntry?.(), file: item.getAsFile?.() }))
    const files = []
    let hasDirectory = false
    const add = (file, path) => {
        if (files.length >= 5000) throw new Error('文件夹内容过多，请选择更小的子目录')
        files.push({ file, name: file.name, size: file.size, webkitRelativePath: path })
    }
    const walk = async (entry, path) => {
        if (entry.isFile) {
            const file = await new Promise((resolve, reject) => entry.file(resolve, reject))
            add(file, path)
        } else if (entry.isDirectory) {
            hasDirectory = true
            if (path.split('/').some(p => p.startsWith('.') || p === '__MACOSX')) { files.push({ name: entry.name, size: 0, webkitRelativePath: path, file: null }); return }
            const reader = entry.createReader()
            for (;;) {
                const children = await new Promise((resolve, reject) => reader.readEntries(resolve, reject))
                if (!children.length) break
                for (const child of children) await walk(child, `${path}/${child.name}`)
            }
        }
    }
    for (const { entry, file } of entries) {
        if (entry) await walk(entry, entry.name)
        else if (file) add(file, file.name)
    }
    return { files, hasDirectory }
}
