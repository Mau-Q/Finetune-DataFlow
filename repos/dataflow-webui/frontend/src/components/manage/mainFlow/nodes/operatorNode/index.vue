<template>
    <base-node v-bind="props" :data="displayData" :theme="theme">
        <div class="fv-loading-block">
            <fv-progress-ring v-if="loading" :loading="true" :r="18" :border-width="3" background="white"
                :color="thisData.borderColor"></fv-progress-ring>
        </div>
        <div class="operator-compact-summary" @mousedown.stop>
            <div class="operator-summary-row">
                <span class="step-pill">{{ stepLabel }}</span>
                <span v-if="reportedStep" class="node-execution-state" :class="reportedStep.status">{{ ({running:'运行中',completed:'已完成',failed:'失败',initializing:'初始化',initialized:'就绪'})[reportedStep.status] || reportedStep.status }}</span>
                <span class="parameter-count">{{ initParamCount }} init · {{ runParamCount }} run</span>
            </div>
            <button class="details-button nodrag nopan" type="button" :aria-label="`${thisData.label} 参数详情`" @pointerdown.stop @pointerup.stop="inspectPointer" @mousedown.stop @dblclick.stop @click.stop="inspect">
                <i class="ms-Icon ms-Icon--Info"></i>
                {{ appConfig.local('参数详情') }}
            </button>
        </div>
    </base-node>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useGlobal } from '@/hooks/general/useGlobal'
import { useAppConfig } from '@/stores/appConfig'
import { useDataflow } from '@/stores/dataflow'
import { useTheme } from '@/stores/theme'

import baseNode from '@/components/manage/mainFlow/nodes/baseNode.vue'

defineOptions({ name: 'OperatorCanvasNode' })

const { $api } = useGlobal()

const emits = defineEmits(['update-node-data', 'inspect-node'])

const props = defineProps({
    id: {
        type: String,
        required: true
    },
    position: {
        type: Object,
        required: true
    },
    selected: {
        type: Boolean,
        default: false
    },
    data: {
        type: Object,
        default: () => ({})
    }
})

const appConfig = useAppConfig()
const _theme = useTheme()
const dataflow = useDataflow()

const theme = computed(() => {
    return _theme.theme
})

const defaultData = {
    label: 'Operator',
    status: 'Operator',
    nodeInfo: '',
    background: '',
    titleColor: '',
    statusColor: 'rgba(90, 90, 90, 1)',
    infoTitleColor: 'rgba(28, 28, 30, 1)',
    borderColor: '',
    shadowColor: '',
    groupBackground: 'rgba(255, 255, 255, 0.8)',
    enableDelete: true
}
const thisData = computed(() => {
    return {
        ...defaultData,
        ...props.data,
        shadowColor: props.data.nodeShadowColor ? props.data.nodeShadowColor : 'rgba(0, 0, 0, 0.05)'
    }
})
const hiddenParam = (item) => {
    let filter_keys = ['storage'];
    if (filter_keys.includes(item.name)) return false
    return true
}

const compactDescription = computed(() => {
    let text = String(
        thisData.value.pipelineRole || thisData.value.nodeInfo || thisData.value.description || ''
    )
        .replace(/\s+/g, ' ')
        .replace(/^[\s('"“]+/, '')
        .trim()
    if (!text) return ''

    const sectionMarkers = ['输入参数', '主要功能', '处理流程包括', '输出格式如下']
    const sectionIndex = sectionMarkers
        .map((marker) => text.indexOf(marker))
        .filter((index) => index > 0)
        .sort((a, b) => a - b)[0]
    if (sectionIndex) text = text.slice(0, sectionIndex).trim()

    const sentenceEnd = text.search(/[。！？]/)
    if (sentenceEnd >= 0) text = text.slice(0, sentenceEnd + 1)
    text = text.replace(/[\s,'"”]+$/, '')
    return /[。！？.!?]$/.test(text) ? text : `${text}。`
})
const reportedStep = computed(() => {
    const index = (thisData.value.pipeline_idx || 0) - 1
    return Object.values(dataflow.execution?.operators_detail || {}).find(step => step.index === index && step.name === thisData.value.name)
})
const displayData = computed(() => ({
    ...thisData.value,
    nodeInfo: compactDescription.value,
    compact: true,
    executionStatus: reportedStep.value?.status || ''
}))
const visibleRunParams = computed(() => thisData.value.operatorParams?.run?.filter(hiddenParam) || [])
const initParamCount = computed(() => thisData.value.operatorParams?.init?.filter((item) => item.show).length || 0)
const runParamCount = computed(() => visibleRunParams.value.length)
const stepLabel = computed(() => thisData.value.pipeline_idx ? `Step ${thisData.value.pipeline_idx}` : 'Operator')

const loading = ref(false) // for data loading display
const paramsWrapper = (objs) => {
    for (let item of objs) {
        if (item.value === undefined) item.value = item.default_value ?? null
        item.show = true
        if (item.name === 'prompt_template') {
            let val = item.value
            if (typeof val === 'string' && val.startsWith('user_prompt:')) {
                item.value = { ref: val }
            } else if (typeof (val) === 'string') {
                if (val.indexOf("'") > -1) {
                    val = val.match(/'(.*)'/)
                    if (val) {
                        val = val[1]
                        val = val.split('.')
                        val = val[val.length - 1]
                    } else val = ''
                }
                let promptInfo = dataflow.promptInfo[val]
                let promptParams = []
                if (promptInfo && promptInfo.parameter.init)
                    promptParams = promptInfo.parameter.init
                promptParams.forEach((param) => {
                    param.value = param.default_value ?? null
                })
                item.value = {
                    cls_name: val,
                    params: promptParams
                }
            }
            else item.value = val
            item.show = false
        }
    }
    return objs
}
let detailRequest = 0
let detailKey = ''
const getNodeDetail = async () => {
    if (props.data.externalTemplate || !props.data?.name || !props.data?.flowId) return
    const id = props.id, name = props.data.name
    const key = JSON.stringify([id, name])
    if (loading.value && detailKey === key) return
    detailKey = key
    const request = ++detailRequest
    loading.value = true
    emits('update-node-data', {id, data: {parameterLoading: true, parameterError: ''}})
    try {
        let parameter = props.data._cache_parameter
        if (!parameter) {
            const res = await $api.operators.get_operator_detail_by_name(name)
            if (res?.code !== 200 || !res.data?.parameter) throw new Error(res?.message || '参数加载失败，请再次点击参数详情重试')
            parameter = res.data.parameter
        }
        if (request !== detailRequest || props.id !== id || props.data.name !== name) return
        const operatorParams = props.data.operatorParams || {
            init: paramsWrapper(JSON.parse(JSON.stringify(parameter.init || []))),
            run: paramsWrapper(JSON.parse(JSON.stringify(parameter.run || [])))
        }
        emits('update-node-data', {id, data: {operatorParams, _cache_parameter: parameter, parameterLoading: false, parameterError: ''}})
    } catch(e) {
        if (request === detailRequest && props.id === id) emits('update-node-data', {id, data: {parameterLoading: false, parameterError: e.message || '参数加载失败，请再次点击参数详情重试'}})
    } finally { if (request === detailRequest) loading.value = false }
}
// Vue Flow's drag handler can suppress the synthetic click after a pan/drag.
// Handle primary pointer release as well; keyboard activation still uses click.
const inspectPointer = (event) => { if (event.button === 0) inspect() }
const inspect = () => {
    emits('inspect-node', props.id)
    if (!props.data.operatorParams || props.data.parameterError) getNodeDetail()
}

watch([() => props.id, () => props.data.name], () => getNodeDetail())

watch(
    () => dataflow.executionStep,
    () => {
        syncLoading()
    }
)

watch(
    () => dataflow.execution.status,
    () => {
        syncLoading()
    }
)
const syncLoading = () => {
    if (!dataflow.execution) return null
    if (!dataflow.execution.task_id) return null
    let pipeline_idx = thisData.value.pipeline_idx - 1
    let current_step = dataflow.executionStep
    const loading = current_step === pipeline_idx && ['running', 'pending', 'queued'].includes(dataflow.execution.status)
    emits('update-node-data', {
        id: props.id,
        data: { ...props.data, loading }
    })
}

onMounted(async () => {
    await getNodeDetail()
    syncLoading()
})

</script>

<style lang="scss">
.df-flow-default-node {
    .node-execution-state { font-size:10px; color:#78849a; &.running {color:#5965d8} &.completed {color:#299668} &.failed {color:#d65663} }
    .fv-loading-block {
        @include HcenterVcenter;
    }

    .log-list {
        position: relative;
        width: 100%;
        height: auto;
        max-height: 200px;
        padding: 3px;
        background: black;
        font-size: 8px;
        color: rgba(193, 252, 167, 1);
        border-radius: 3px;
        overflow: overlay;
    }

    .operator-compact-summary {
        width: calc(100% - 20px);
        height: 100%;
        margin: 0px 10px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;

        .operator-summary-row {
            min-width: 0;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .step-pill {
            width: fit-content;
            padding: 2px 7px;
            color: var(--node-border-color);
            background: color-mix(in srgb, var(--node-border-color) 12%, transparent);
            border-radius: 999px;
            font-size: 10px;
            font-weight: 700;
        }

        .parameter-count {
            color: var(--node-status-color);
            font-size: 10px;
            white-space: nowrap;
        }

        .details-button {
            min-height: 32px;
            padding: 0px 10px;
            flex-shrink: 0;
            color: #fff;
            background: var(--node-border-color);
            border: 1px solid var(--node-border-color);
            border-radius: 7px;
            font-size: 10px;
            cursor: pointer;

            i {
                margin-right: 3px;
            }

            &:hover {
                filter: brightness(1.12);
            }
        }
    }

}
</style>
