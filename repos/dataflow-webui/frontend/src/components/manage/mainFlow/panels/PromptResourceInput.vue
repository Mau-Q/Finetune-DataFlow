<template>
    <div class="prompt-resource-input">
        <label>{{ contract?.label || '自定义模板' }}</label>
        <p v-if="contract">{{ contract.protocol }}</p>
        <p v-if="!supported">此位置尚未接入经过验证的自定义 Prompt 契约，保留内置模板。</p>
        <template v-else>
            <div class="resource-choice">
                <native-select :model-value="selectedRef" :theme="theme" label="自定义模板" :options="templateOptions" @update:modelValue="selectTemplate" />
                <fv-button :theme="theme" :border-radius="6" @click="load">刷新</fv-button>
            </div>
            <router-link :to="managerLocation">管理模板</router-link>
            <div v-for="variable in (freeBindings || isMM ? variables : [])" :key="variable" class="binding-row">
                <label :for="`binding-${variable}`">{{ variable }}</label>
                <native-text :model-value="bindings[variable] || ''" :theme="theme" :label="`变量 ${variable} 的数据列`" placeholder="数据列名" @update:modelValue="setBinding(variable,$event)" />
            </div>
            <p v-if="selectedRef && !isMM">任务启动时固定内容；修改模板后，新任务使用新内容。</p><p v-else-if="isMM">保存仅更新配置；尚未执行视觉生成。</p>
        </template>
        <p v-if="error" role="alert">{{ error }}</p>
    </div>
</template>
<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import axios from 'axios'
import { useRoute } from 'vue-router'
import NativeSelect from '@/components/manage/forms/NativeSelect.vue'
import NativeText from '@/components/manage/forms/NativeText.vue'
import {subscribeChanges} from '@/components/manage/forms/changes'
import {useTheme} from '@/stores/theme'
const theme=computed(()=>useTheme().theme)
const route = useRoute()
const emit = defineEmits(['update-value'])
const props = defineProps({ item: Object, data: Object })
const managerLocation = computed(() => ({ path:'/m/prompts', query:{ operator:props.data.name||props.data.label, relation:'compatible', ...(route.query.pipeline ? {pipeline:'pipeline:'+route.query.pipeline}: {}) } }))
const templates = ref([]), variables = ref([]), error = ref(''), contracts=ref({})
const operatorName=computed(()=>props.data.name || props.data.label)
const isMM=computed(()=>props.data.externalTemplate && ['question','answer'].includes(props.data.mmStepId))
const mmDefault=computed(()=>`builtin:mm-${props.data.mmStepId}-v1`)
const contract=computed(()=>isMM.value?{label:props.data.mmStepId==='answer'?'图片答案模板':'图片问题模板',required:props.data.mmStepId==='answer'?['question']:[],variables:null,protocol:'图片输入保持为当前材料。答案必须保留 {question} 并绑定上游问题；当前 MM 执行尚未启用。'}:contracts.value[operatorName.value]?.[props.item.name])
const freeBindings=computed(()=>operatorName.value==='FormatStrPromptedGenerator')
const supported = computed(() => !!contract.value)
const selectedRef = computed(() => isMM.value ? props.item.value : typeof props.item.value === 'string' && props.item.value.startsWith('user_prompt:') ? props.item.value : props.item.value?.ref || '')
const bindings = computed(() => isMM.value ? Object.fromEntries((props.data.operatorParams?.run || []).filter(p=>p.name.startsWith('binding_')).map(p=>[p.name.slice(8),p.value])) : props.item.value?.bindings || {})
let loadVersion=0, variableVersion=0,stopChanges
const templateOptions=computed(()=>[{value:isMM.value?mmDefault.value:'',label:'使用内置 Prompt'},...(selectedRef.value&&selectedRef.value!==mmDefault.value&&!templates.value.some(t=>`user_prompt:${t.id}`===selectedRef.value)?[{value:selectedRef.value,label:`引用不存在：${selectedRef.value}`}]:[]),...templates.value.map(t=>({value:`user_prompt:${t.id}`,label:t.name}))])
async function load() {
    const version=++loadVersion
    try {
        const [res, rules] = await Promise.all([axios.get('/api/v1/prompts/user'),axios.get('/api/v1/prompts/contracts')])
        if(!rules.data?.success)throw new Error(rules.data?.message || '契约读取失败')
        if (!res.data?.success) throw new Error(res.data?.message || '模板读取失败')
        if(version!==loadVersion)return
        contracts.value=rules.data.data
        templates.value = res.data.data.filter(t => !t.allowed_operators?.length || t.allowed_operators.includes(operatorName.value))
        error.value = ''
        await updateVariables()
    } catch (e) { if(version===loadVersion)error.value = e.message }
}
async function updateVariables() {
    const version=++variableVersion
    const selected = selectedRef.value
    const record = templates.value.find(t => `user_prompt:${t.id}` === selected)
    variables.value = []
    if (!record) {
        if(isMM.value && selectedRef.value===mmDefault.value){variables.value=props.data.mmStepId==='answer'?['question']:[];syncMMBindings(variables.value)}
        return
    }
    try {
        const res = await axios.post('/api/v1/prompts/user/preview', { template: record.template, variables: {} })
        if (!res.data?.success) throw new Error(res.data?.message || '模板校验失败')
        if (version===variableVersion && selectedRef.value === selected) {
            variables.value = res.data.data.placeholders
            if(isMM.value)syncMMBindings(variables.value)
            const rule=contract.value
            const missing=(rule?.required || []).filter(k=>!variables.value.includes(k))
            const extra=rule?.variables && variables.value.filter(k=>!rule.variables.includes(k))
            error.value=missing.length?`模板必须包含变量：${missing.join('、')}`:extra?.length?`此位置不接受变量：${extra.join('、')}`:''
        }
    } catch (e) { if(version===variableVersion && selectedRef.value===selected)error.value = e.message }
}
function syncMMBindings(fields) {
    const params=props.data.operatorParams.run
    const current=bindings.value
    params.splice(0,params.length,...params.filter(p=>!p.name.startsWith('binding_')),...fields.map(key=>({name:`binding_${key}`,value:current[key] || params.find(p=>p.name===`input_${key}`)?.value || '',show:true})))
}
function selectTemplate(value) {
    if(isMM.value){emit('update-value',value || mmDefault.value);error.value='';return}
    if (!value) { emit('update-value', null); error.value=''; return }
    emit('update-value', freeBindings.value?{ ref: value, bindings: {} }:{ref:value})
}
function setBinding(key, value) {
    if(isMM.value){const item=props.data.operatorParams.run.find(p=>p.name===`binding_${key}`);if(item)item.value=value;return}
    emit('update-value', { ref: selectedRef.value, bindings: { ...bindings.value, [key]: value } })
}
watch(selectedRef, updateVariables)
watch(()=>[operatorName.value,props.item.name],load)
onMounted(()=>{load();stopChanges=subscribeChanges(change=>{if(change.topic==='resources')load()})})
onUnmounted(()=>{stopChanges?.();loadVersion++;variableVersion++})
</script>
<style scoped>
.prompt-resource-input { font-size: 12px; padding: 10px 0; }
p { color: #78849a; line-height: 1.6; margin: 5px 0; }
.resource-choice, .binding-row { display: flex; gap: 8px; margin: 7px 0; align-items: center; }
select, input { width: 100%; min-width: 0; padding: 7px; border: 1px solid #8992a4; border-radius: 5px; background: transparent; color: inherit; }
.binding-row label { min-width: 70px; overflow-wrap: anywhere; }
a { color: #6376df; }
button { color: inherit; background: transparent; border: 1px solid #8992a4; border-radius: 5px; white-space: nowrap; padding: 6px; }
</style>
