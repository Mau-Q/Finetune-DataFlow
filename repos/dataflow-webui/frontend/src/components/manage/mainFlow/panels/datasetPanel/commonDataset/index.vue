<template>
    <section class="source-selector" :class="{ dark: theme === 'dark' }">
        <template v-if="showAdd"
            ><div class="heading"><h2>添加原始数据集</h2></div>
            <source-dataset-import @cancel="showAdd = false" @created="created"
        /></template>
        <template v-else-if="selected">
            <div class="heading">
                <button @click="back">← 返回列表</button
                ><button class="primary" @click="$emit('confirm', selected)">选择此数据集</button>
            </div>
            <h2>{{ selected.name }}</h2>
            <p class="summary">{{ sourceType(selected) }} · {{ sourceCount(selected) }}</p>
            <p v-if="previewBusy" class="empty">正在加载内容…</p>
            <template v-else-if="hasFiles">
                <label class="file-select"
                    >原文件<select v-model.number="sourceIndex">
                        <option v-for="(row, i) in rows" :key="i" :value="i">
                            {{ offset + i + 1 }}. {{ fileName(row) }}
                        </option>
                    </select></label
                >
                <img
                    v-if="isImage"
                    :src="fileUrl"
                    :alt="fileName(currentFile)"
                    class="image-preview"
                />
                <iframe
                    v-else-if="isPdf"
                    :src="fileUrl"
                    title="原始 PDF 预览"
                    class="file-preview"
                />
                <p v-else-if="memberBusy" class="empty">正在加载文件内容…</p>
                <pre v-else>{{
                    memberRows.length
                        ? JSON.stringify(memberRows, null, 2)
                        : '此文件没有可预览的记录。'
                }}</pre>
                <a :href="fileUrl" target="_blank" rel="noopener">打开原文件 ↗</a>
            </template>
            <pre v-else-if="rows.length">{{ JSON.stringify(rows, null, 2) }}</pre>
            <p v-else-if="!previewBusy" class="empty">暂无可预览的内容。</p>
            <div v-if="selected.num_samples > 20" class="pagination">
                <button :disabled="previewBusy || offset === 0" @click="page(-20)">上一页</button
                ><span
                    >{{ offset + 1 }}–{{ Math.min(offset + 20, selected.num_samples) }} /
                    {{ selected.num_samples }}</span
                ><button
                    :disabled="previewBusy || offset + 20 >= selected.num_samples"
                    @click="page(20)"
                >
                    下一页
                </button>
            </div>
            <details>
                <summary>属性与来源</summary>
                <dl>
                    <dt>数据集 ID</dt>
                    <dd>{{ selected.id }}</dd>
                    <dt>文件位置</dt>
                    <dd>{{ selected.root }}</dd>
                    <dt>更新时间</dt>
                    <dd>{{ formatTime(recordTime(selected)) }}</dd>
                </dl>
                <router-link
                    :to="{ path: '/m/materials', query: { dataset: selected.id } }"
                    target="_blank"
                    >在原始数据集页面查看完整详情 ↗</router-link
                >
            </details>
        </template>
        <template v-else>
            <div class="heading">
                <p>选择原始数据集加入画布。</p>
                <div class="actions">
                    <button :disabled="loading" @click="reload">刷新</button
                    ><button class="primary" @click="showAdd = true">＋ 添加数据集</button>
                </div>
            </div>
            <div class="filters">
                <input
                    v-model="search"
                    aria-label="搜索原始数据集"
                    placeholder="搜索数据集名称"
                    type="search"
                /><select v-model="kind" aria-label="数据形式">
                    <option value="">全部数据形式</option>
                    <option
                        v-for="name in ['PDF', '图片', '文本', '结构化数据', '混合']"
                        :key="name"
                    >
                        {{ name }}
                    </option>
                </select>
            </div>
            <div class="table-scroll">
                <table>
                    <thead>
                        <tr>
                            <th>数据集名称</th>
                            <th>数据形式</th>
                            <th>数量</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="item in filtered" :key="item.id">
                            <td>
                                <button class="name-link" @click="open(item)">
                                    {{ item.name }}
                                </button>
                            </td>
                            <td>{{ sourceType(item) }}</td>
                            <td>{{ sourceCount(item) }}</td>
                            <td class="actions">
                                <button
                                    class="link"
                                    :aria-label="`查看 ${item.name}`"
                                    @click="open(item)"
                                >
                                    查看</button
                                ><button
                                    class="primary"
                                    :aria-label="`选择 ${item.name}`"
                                    @click="$emit('confirm', item)"
                                >
                                    选择
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
                <p v-if="!filtered.length" class="empty">
                    {{ loading ? '正在加载…' : '没有匹配的原始数据集' }}
                </p>
            </div>
            <p class="summary">{{ filtered.length }} 个原始数据集</p>
        </template>
        <p v-if="notice" role="status" class="notice">{{ notice }}</p>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
    </section>
</template>
<script>
import axios from 'axios'
import { mapState, mapActions } from 'pinia'
import { useDataflow } from '@/stores/dataflow'
import { useTheme } from '@/stores/theme'
import SourceDatasetImport from '@/components/manage/library/SourceDatasetImport.vue'
import {
    sourceType,
    sourceCount,
    recentFirst,
    formatTime,
    recordTime
} from '@/views/manage/library/catalog.js'
export default {
    name: 'SourceDatasetSelector',
    components: { SourceDatasetImport },
    emits: ['confirm'],
    data: () => ({
        showAdd: false,
        search: '',
        kind: '',
        selected: null,
        rows: [],
        memberRows: [],
        sourceIndex: 0,
        offset: 0,
        loading: false,
        previewBusy: false,
        memberBusy: false,
        error: '',
        notice: '',
        requestVersion: 0,
        memberVersion: 0
    }),
    computed: {
        ...mapState(useDataflow, ['visibleDatasets']),
        ...mapState(useTheme, ['theme']),
        filtered() {
            return recentFirst(
                this.visibleDatasets.filter(
                    (r) =>
                        r.name.toLowerCase().includes(this.search.toLowerCase()) &&
                        (!this.kind || sourceType(r) === this.kind)
                )
            )
        },
        hasFiles() {
            return (
                this.rows.length > 0 &&
                this.rows.every(
                    (r) =>
                        r &&
                        typeof r.source === 'string' &&
                        Object.keys(r).every((k) =>
                            ['source', 'source_name', 'material_id'].includes(k)
                        )
                )
            )
        },
        currentFile() {
            return this.rows[this.sourceIndex]
        },
        isPdf() {
            return /\.pdf$/i.test(this.currentFile?.source || '')
        },
        isImage() {
            return /\.(png|jpe?g|webp|gif|bmp)$/i.test(this.currentFile?.source || '')
        },
        fileUrl() {
            return `/api/v1/library/inputs/${this.selected.id}/file?row=${this.offset + this.sourceIndex}`
        }
    },
    watch: {
        sourceIndex() {
            this.loadMember()
        }
    },
    mounted() {
        this.reload()
    },
    beforeUnmount() {
        this.requestVersion++
        this.memberVersion++
    },
    methods: {
        sourceType,
        sourceCount,
        formatTime,
        recordTime,
        ...mapActions(useDataflow, ['getDatasets']),
        async reload() {
            this.loading = true
            this.error = ''
            try {
                await this.getDatasets()
            } catch (e) {
                this.error = e.message
            } finally {
                this.loading = false
            }
        },
        async request(path) {
            const r = await axios.get('/api/v1' + path)
            if (!r.data.success) throw new Error(r.data.message)
            return r.data.data
        },
        async created(record) {
            this.showAdd = false
            await this.reload()
            this.notice = `已添加「${record.name}」`
        },
        fileName(row) {
            return row?.source_name || (row?.source || '').split(/[\\/]/).pop() || '原文件'
        },
        back() {
            this.requestVersion++
            this.memberVersion++
            this.selected = null
            this.rows = []
            this.error = ''
        },
        async open(item) {
            this.selected = item
            this.offset = 0
            await this.loadPreview()
        },
        async page(delta) {
            this.offset += delta
            await this.loadPreview()
        },
        async loadPreview() {
            const version = ++this.requestVersion
            this.memberVersion++
            this.previewBusy = true
            this.error = ''
            this.rows = []
            this.memberRows = []
            this.sourceIndex = 0
            try {
                const rows = await this.request(
                    `/library/inputs/${this.selected.id}/preview?offset=${this.offset}&limit=20`
                )
                if (version !== this.requestVersion) return
                this.rows = rows
                await this.loadMember()
            } catch (e) {
                if (version === this.requestVersion)
                    this.error = e.response?.data?.message || e.message
            } finally {
                if (version === this.requestVersion) this.previewBusy = false
            }
        },
        async loadMember() {
            const version = ++this.memberVersion
            this.memberRows = []
            if (!this.selected || !this.hasFiles || this.isPdf || this.isImage) return
            this.memberBusy = true
            try {
                const rows = await this.request(
                    `/library/inputs/${this.selected.id}/member-preview?row=${this.offset + this.sourceIndex}`
                )
                if (version === this.memberVersion) this.memberRows = rows
            } catch (e) {
                if (version === this.memberVersion)
                    this.error = e.response?.data?.message || e.message
            } finally {
                if (version === this.memberVersion) this.memberBusy = false
            }
        }
    }
}
</script>
<style scoped>
.source-selector {
    width: 100%;
    height: 100%;
    overflow: auto;
    color: #25334c;
    font-size: 14px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
.heading,
.actions,
.filters,
.pagination {
    display: flex;
    align-items: center;
    gap: 10px;
    justify-content: space-between;
}
.heading {
    margin-bottom: 18px;
}
.heading p,
.summary {
    color: #78849a;
    font-size: 12px;
}
.actions {
    justify-content: flex-end;
}
.filters {
    margin-bottom: 18px;
}
.filters input {
    flex: 1;
    min-width: 120px;
}
button,
input,
select {
    font: inherit;
    color: inherit;
    border: 1px solid #d9dfeb;
    border-radius: 7px;
    background: white;
    padding: 8px 12px;
    box-sizing: border-box;
}
button {
    cursor: pointer;
}
button:disabled {
    opacity: 0.5;
    cursor: default;
}
.primary {
    background: #535fd6;
    color: white;
    border-color: #535fd6;
}
.link,
.name-link {
    background: transparent;
    border: 0;
    padding: 0;
    color: #535fd6;
    text-align: left;
}
.name-link {
    font-weight: 600;
}
.table-scroll {
    border: 1px solid #e2e7f0;
    border-radius: 10px;
    overflow: auto;
}
table {
    width: 100%;
    border-collapse: collapse;
    text-align: left;
}
th,
td {
    padding: 14px 16px;
    border-bottom: 1px solid #edf0f5;
}
th {
    font-size: 12px;
    font-weight: 500;
    color: #78849a;
    background: #fafbfe;
}
td:first-child {
    min-width: 210px;
}
td:nth-child(2),
td:nth-child(3) {
    white-space: nowrap;
}
.summary {
    margin-top: 14px;
}
.empty {
    text-align: center;
    padding: 30px;
    color: #78849a;
}
h2 {
    font-size: 18px;
    margin: 16px 0 6px;
}
pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    background: #f4f6fa;
    padding: 16px;
    border-radius: 8px;
    line-height: 1.7;
    max-height: 400px;
    overflow: auto;
}
details {
    margin-top: 20px;
    border-top: 1px solid #edf0f5;
    padding-top: 14px;
    font-size: 12px;
}
summary {
    cursor: pointer;
    color: #78849a;
}
dl {
    display: grid;
    grid-template-columns: 90px minmax(0, 1fr);
    gap: 12px;
}
dd {
    margin: 0;
    overflow-wrap: anywhere;
}
dt {
    color: #78849a;
}
.file-select {
    display: flex;
    gap: 10px;
    align-items: center;
    margin: 16px 0;
}
.file-select select {
    min-width: 0;
    flex: 1;
}
.image-preview {
    display: block;
    max-width: 100%;
    max-height: 360px;
    margin: 16px auto;
}
.file-preview {
    width: 100%;
    height: 380px;
    border: 1px solid #e2e7f0;
    border-radius: 8px;
    margin-bottom: 12px;
}
.pagination {
    justify-content: center;
    margin-top: 12px;
}
.notice,
.error {
    padding: 12px;
    border-radius: 7px;
    margin-top: 12px;
}
.notice {
    color: #306448;
    background: #e9f4ed;
}
.error {
    color: #ae342b;
    background: #fff0ed;
}
a {
    color: #535fd6;
}
.dark {
    color: #dfe5ef;
}
.dark button,
.dark input,
.dark select {
    background: #292e39;
    color: inherit;
    border-color: #424b5b;
}
.dark button.primary {
    background: #535fd6;
}
.dark th,
.dark pre {
    background: #252a35;
}
.dark th,
.dark td,
.dark .table-scroll,
.dark details {
    border-color: #424b5b;
}
.dark .link,
.dark .name-link,
.dark a {
    color: #b7c0ff;
}
</style>
