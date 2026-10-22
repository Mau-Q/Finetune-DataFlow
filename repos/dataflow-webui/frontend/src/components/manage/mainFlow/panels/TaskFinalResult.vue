<template>
    <section class="task-final-result" :class="{ dark: theme === 'dark' }">
        <p v-if="loading" role="status">正在加载最终结果…</p>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <template v-if="result && !loading">
            <h3>最终结果</h3>
            <p v-if="result.storage_error" role="alert" class="error">{{ result.storage_error }}</p>
            <p v-if="result.sample_summary?.invalid" class="help" role="status">有效 {{ result.sample_summary.valid }} 条，无效 {{ result.sample_summary.invalid }} 条。无效样本已单独记录，不影响其余结果导出。</p>
            <a v-if="result.invalid_artifact" :href="`/api/v1/generation/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(result.invalid_artifact)}`" download>下载无效样本记录</a>
            <p v-if="result.invalid_samples_file" class="help">无效样本记录：{{ result.invalid_samples_file }}</p>
            <details v-if="result.result_directory"><summary>本次结果目录</summary><p class="directory">{{ result.result_directory }}</p></details>
            <p>任务 {{ result.task_id }} · {{ statusLabel(result.status) }}</p>
            <p v-if="result.reason" class="help">{{ result.reason }}</p>
            <template v-if="result.available">
                <div class="actions"><strong>{{ result.artifact.row_count }} 条样本</strong><a :href="downloadUrl" download>下载最终 JSONL</a></div>
                <details><summary>本地文件与校验信息</summary><dl><dt>文件位置</dt><dd>{{ result.artifact.path }}</dd><dt>SHA-256</dt><dd>{{ result.artifact.sha256 }}</dd></dl></details>
                <details v-for="(row, index) in result.sample_data" :key="index" class="sample"><summary>样本 {{ index + 1 }} · {{ excerpt(row) }}</summary><pre>{{ JSON.stringify(row, null, 2) }}</pre></details>
                <p v-if="result.artifact.row_count > result.sample_data.length" class="help">预览前 {{ result.sample_data.length }} 条；下载可查看全部内容。</p>
            </template>
            <p v-if="result.collectable && !result.collections.length" class="help" role="status">结果已生成，但自动收录尚未完成。可在下方重新收录。</p>
            <p v-if="result.auto_collection?.status === 'failed'" role="alert" class="error">自动收录失败：{{ result.auto_collection.reason }}</p>
            <p v-if="result.auto_collection?.status === 'skipped'" class="help">未自动收录：{{ result.auto_collection.reason }}</p>
            <template v-if="result.collections.length">
                <h4>已收录到生成数据集</h4><ul><li v-for="d in result.collections" :key="d.id"><router-link :to="{ path: '/m/training-datasets', query: { dataset: d.id } }" @click="$emit('navigate')">{{ d.name }} · 当前 {{ d.row_count }} 条 →</router-link></li></ul>
            </template>
            <form v-if="result.collectable && !result.collections.length" @submit.prevent="collect">
                <h4>收录到生成数据集</h4>
                <p class="help">{{ result.modality === 'image_text' ? '图文' : '文本' }} {{ result.training_type.toUpperCase() }} · 相同样本只保留一条，来源任务仍会记录。</p>
                <div class="form-field">收录方式<fv-combobox v-model="modeModel" :theme="theme" :options="modeOptions" :disabled="busy" aria-label="收录方式" style="width:100%" /></div>
                <div class="form-field" v-if="mode === 'new'">数据集名称<fv-text-box v-model="name" :theme="theme" aria-label="数据集名称" :disabled="busy" :border-radius="6" style="width:100%;height:38px" /></div>
                <div class="form-field" v-else>目标数据集<fv-combobox v-model="draftModel" :theme="theme" :options="draftOptions" :disabled="busy" placeholder="请选择同模态、同训练类型的数据集" aria-label="目标数据集" style="width:100%" /></div>
                <p v-if="mode === 'append' && !compatibleDrafts.length" class="help">暂无匹配的数据集，可切换为新建。</p>
                <template v-if="result.media_refs?.length">
                    <p class="help">已从本次输入固定的图片会自动绑定；其他引用请手动选择。追加时可沿用目标已有绑定。</p>
                    <div class="form-field" v-for="ref in result.media_refs" :key="ref">{{ ref }}<fv-combobox :model-value="imageOptions.find(m => m.key === bindings[ref]) || {key:'', text:''}" :theme="theme" :options="imageOptions" :disabled="busy" :placeholder="targetBindings[ref] ? '沿用目标已有图片' : '请选择本地图片材料'" :aria-label="ref" style="width:100%" @update:modelValue="setBinding(ref, $event)" /></div>
                </template>
                <fv-button :theme="theme" :border-radius="6" :disabled="!canCollect" @click="collect">{{ busy ? '正在收录…' : '确认收录' }}</fv-button>
            </form>
        </template>
        <p v-if="notice" role="status" class="notice">{{ notice }}</p>
    </section>
</template>
<script>
import axios from 'axios'
import {publishChange,subscribeChanges} from '@/components/manage/forms/changes'
export default {
    props: { taskId: { type: String, required: true }, theme: { type: String, default: 'light' } },
    emits: ['navigate'],
    data: () => ({ result: null, drafts: [], images: [], loading: false, busy: false, error: '', notice: '', mode: 'new', name: '', draftId: '', bindings: {}, requestId: 0, contextVersion:0, stopChanges:null }),
    computed: {
        modeOptions() { return [{key:'new',text:'新建生成数据集'},{key:'append',text:'追加到已有数据集'}] },
        modeModel: { get() { return this.modeOptions.find(o => o.key === this.mode) }, set(o) { if(o)this.mode = o.key } },
        draftOptions() { return this.compatibleDrafts.map(d => ({key:d.id,text:`${d.name} · ${d.row_count} 条`})) },
        draftModel: { get() { return this.draftOptions.find(o => o.key === this.draftId) || {key:'', text:''} }, set(o) { this.draftId = o?.key || '' } },
        imageOptions() { return this.images.map(m => ({key:m.id,text:m.name})) },
        canCollect() { return !this.busy && (this.mode === 'new' ? !!this.name.trim() && this.name.length <= 240 : !!this.draftId) && (this.result?.media_refs || []).every(ref => this.bindings[ref] || this.targetBindings[ref]) },
        downloadUrl() { return `/api/v1/tasks/execution/${encodeURIComponent(this.taskId)}/final-result/download` },
        compatibleDrafts() { return this.drafts.filter(d => d.modality === this.result?.modality && d.training_type === this.result?.training_type) },
        targetBindings() { return this.mode === 'append' ? this.drafts.find(d => d.id === this.draftId)?.media_bindings || {} : {} }
    },
    mounted(){this.stopChanges=subscribeChanges(change=>{if(change.topic==='datasets'&&!this.busy)this.refreshContext()})},
    beforeUnmount(){this.stopChanges?.()},
    watch: { taskId: { immediate: true, handler() { this.load() } } },
    methods: {
        async refreshContext(){
            const taskId=this.taskId,version=this.requestId,contextVersion=++this.contextVersion
            try{const [result,drafts,materials]=await Promise.all([this.request('get',`/tasks/execution/${encodeURIComponent(taskId)}/final-result`),this.request('get','/library/drafts?visible_only=true'),this.request('get','/library/materials')]);if(taskId===this.taskId&&version===this.requestId&&contextVersion===this.contextVersion&&!this.busy){this.result=result;this.drafts=drafts;this.images=materials.filter(m=>m.kind==='image');if(!drafts.some(d=>d.id===this.draftId))this.draftId=''}}catch(e){if(taskId===this.taskId&&version===this.requestId&&contextVersion===this.contextVersion)this.error=e.message}
        },
        async request(method, path, data) {
            const r = await axios({ method, url: '/api/v1' + path, data })
            if (!r.data.success) throw new Error(r.data.message || '请求失败')
            return r.data.data
        },
        async load() {
            this.contextVersion++
            const requestId = ++this.requestId
            this.loading = true; this.result = null; this.error = ''; this.notice = ''; this.bindings = {}; this.draftId = ''; this.mode = 'new'
            try {
                const [result, drafts, materials] = await Promise.all([
                    this.request('get', `/tasks/execution/${encodeURIComponent(this.taskId)}/final-result`),
                    this.request('get', '/library/drafts?visible_only=true'), this.request('get', '/library/materials')
                ])
                if (requestId !== this.requestId) return
                this.result = result; this.drafts = drafts; this.images = materials.filter(m => m.kind === 'image')
                this.bindings = {...(result.artifact?.media_bindings || {})}
                this.name = `${result.name || 'Pipeline'} · ${result.task_id}`.slice(0, 240)
            } catch (e) { if (requestId === this.requestId) this.error = e.response?.data?.message || e.message }
            finally { if (requestId === this.requestId) this.loading = false }
        },
        setBinding(ref, option) { this.bindings[ref] = option?.key || '' },
        async collect() {
            if (!this.canCollect) return
            const taskId = this.taskId
            this.contextVersion++
            this.busy = true; this.error = ''; this.notice = ''
            try {
                const body = { expected_sha256: this.result.artifact.sha256, media_bindings: this.bindings, ...(this.mode === 'new' ? { name: this.name } : { draft_id: this.draftId }) }
                const collected = await this.request('post', `/tasks/execution/${encodeURIComponent(taskId)}/final-result/collect`, body)
                if (taskId !== this.taskId) return
                const result = await this.request('get', `/tasks/execution/${encodeURIComponent(taskId)}/final-result`)
                if (taskId !== this.taskId) return
                this.result = result
                this.drafts = [...this.drafts.filter(d => d.id !== collected.id), collected]
                publishChange('datasets',collected.id)
                this.notice = collected.reused ? `此结果已收录到「${collected.name}」，未重复写入。` : `已收录到「${collected.name}」：新增 ${collected.added} 条，跳过重复 ${collected.duplicates_skipped} 条。`
            } catch (e) { if (taskId === this.taskId) this.error = e.response?.data?.message || e.message }
            finally { this.busy = false }
        },
        statusLabel(s) { return { completed: '已完成', failed: '失败', running: '运行中', queued: '排队中', cancelled: '已取消' }[s] || s },
        excerpt(row) { return String(row?.instruction || row?.prompt || row?.messages?.[0]?.content || row?.question || '查看原始数据').slice(0, 80) }
    }
}
</script>
<style scoped>
.task-final-result{padding:16px;background:#fff;color:#26334d;border:1px solid #d9dfeb;border-radius:8px;overflow-wrap:anywhere}.task-final-result.dark{background:#252833;color:#eee}h3{margin:0 0 10px}h4{margin:18px 0 10px}p{line-height:1.6}.form-field{display:block;margin:12px 0}summary{padding:10px 0;cursor:pointer}.sample{border-bottom:1px solid #d9dfeb}pre{white-space:pre-wrap;max-height:300px;overflow:auto;font-size:12px}dd{margin:6px 0 12px;font-size:12px}.help{color:#718096;font-size:13px}.error{color:#b63830}.notice{color:#28713e}.actions{display:flex;gap:16px;align-items:center}a{color:#4e5bd5}
</style>
