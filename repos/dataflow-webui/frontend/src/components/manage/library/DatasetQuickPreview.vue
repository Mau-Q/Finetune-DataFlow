<template>
    <base-panel :model-value="!!dataset" :title="dataset ? `${dataset.name} · 样本预览` : '样本预览'" :theme="theme" width="min(760px, 94vw)" height="80%" @update:modelValue="value => { if (!value) $emit('close') }">
        <template #content>
            <div class="quick-preview" :class="{ dark: theme === 'dark' }">
                <p v-if="loading" role="status">正在加载样本…</p><p v-if="error" role="alert">{{ error }}</p>
                <template v-if="result"><p class="preview-count">共 {{ result.row_count }} 条样本 · 预览前 {{ result.rows.length }} 条</p>
                    <article v-for="(row,index) in result.rows" :key="index"><h3>样本 {{ index + 1 }}</h3><dl><template v-for="(value,key) in row" :key="key"><dt>{{ key }}</dt><dd><template v-if="key === 'messages' && Array.isArray(value)"><div v-for="(message,index) in value" :key="index" class="preview-message"><strong>{{ ({user:'用户',assistant:'回答',system:'系统',tool:'工具'})[message.role] || message.role }}</strong><p>{{ display(message.content) }}</p></div></template><template v-else>{{ display(value) }}</template></dd></template></dl>
                        <img v-for="id in rowImages(row)" :key="id" :src="`/api/v1/library/materials/${encodeURIComponent(id)}/file`" alt="样本图片" />
                    </article><p v-if="!result.rows.length">当前数据集还没有样本。</p></template>
            </div>
        </template>
        <template #control>
            <fv-button :theme="theme" border-radius="6" style="width:80px;height:32px" @click="$emit('close')">关闭</fv-button>
            <fv-button v-if="dataset" :theme="theme" border-radius="6" style="width:160px;height:32px" @click="$emit('open', dataset.id)">查看完整数据集 →</fv-button>
        </template>
    </base-panel>
</template>
<script setup>
import { ref, watch } from 'vue'
import axios from 'axios'
import BasePanel from '@/components/general/basePanel.vue'
const props = defineProps({ dataset: Object, theme: String })
defineEmits(['close', 'open'])
const loading = ref(false), result = ref(null), error = ref('')
let version = 0
watch(() => props.dataset, async dataset => {
    const request = ++version
    result.value = null; error.value = ''; loading.value = false
    if (!dataset) return
    loading.value = true
    try {
        const response = await axios.get(`/api/v1/library/drafts/${encodeURIComponent(dataset.id)}?offset=0&limit=3`)
        if (request !== version) return
        if (!response.data.success) throw new Error(response.data.message || '无法预览样本')
        result.value = response.data.data
    } catch (e) { if(request===version)error.value=e.response?.data?.message || e.message }
    finally { if(request===version)loading.value=false }
}, { immediate: true })
function display(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2) }
function rowImages(row) {
    const text = JSON.stringify(row)
    return [...new Set(Object.entries(result.value?.media_bindings || {}).filter(([ref]) => text.includes(ref)).map(([,id]) => id))]
}
</script>
<style scoped>
.quick-preview{overflow:auto;min-height:0;width:100%;font-size:13px;color:#39465d;line-height:1.7}.quick-preview.dark{color:#dce1ed}.preview-message{padding:8px 10px;border-radius:6px;background:#8080800a;margin-bottom:8px}.preview-message strong{font-size:11px;color:#78849a}.preview-message p{margin:4px 0 0;white-space:pre-wrap}.preview-count{color:#78849a;margin-bottom:14px}.quick-preview article{padding:16px 0;border-top:1px solid #80808025}.quick-preview h3{font-size:14px;margin-bottom:10px}.quick-preview dl{display:grid;grid-template-columns:100px minmax(0,1fr);gap:8px 14px;margin:0}.quick-preview dt{color:#78849a;overflow-wrap:anywhere}.quick-preview dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto}.quick-preview img{max-width:100%;max-height:240px;object-fit:contain;margin-top:12px;border-radius:6px}@media(max-width:600px){.quick-preview dl{grid-template-columns:1fr;gap:4px}.quick-preview dd{margin-bottom:10px}}
</style>
