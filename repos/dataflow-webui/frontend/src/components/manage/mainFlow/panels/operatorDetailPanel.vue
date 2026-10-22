<template>
    <aside v-if="modelValue" class="operator-detail-drawer" :class="{ dark: theme === 'dark' }"
        @mousedown.stop @click.stop @keydown.esc="close" aria-label="算子参数详情">
        <header class="operator-detail-header">
            <p>{{ data?.label || data?.name || appConfig.local('Operator') }}</p>
            <button type="button" :title="appConfig.local('Close')" @click="close">
                <i class="ms-Icon ms-Icon--Cancel"></i>
            </button>
        </header>
        <div class="operator-detail-panel">
                <div class="operator-detail-scroll" @wheel.stop>
                <div class="operator-detail-summary">
                    <span class="step-pill">{{ stepLabel }}</span>
                    <div>
                        <p class="operator-name">{{ data?.name || data?.label }}</p>
                        <p class="operator-description">{{ data?.nodeInfo || data?.description }}</p>
                    </div>
                </div>

                    <p v-if="data?.parameterLoading" role="status">正在加载参数…</p>
                    <p v-if="data?.parameterError" role="alert">{{ data.parameterError }}</p>
                    <section class="parameter-section">
                        <div class="section-heading init">
                            <span>{{ appConfig.local('Init. Parameters') }}</span>
                            <span class="count">{{ visibleInitParams.length + promptTemplateItems.length }}</span>
                        </div>

                        <prompt-resource-input v-for="item in promptTemplateItems" :key="item.name" :item="item" :data="data" @update-value="item.value = $event;emits('edited')" />
                        <div v-if="allowedPrompts.length > 0 && promptTemplateItem && !isResourcePrompt" class="parameter-field">
                            <span class="field-label">{{ appConfig.local('Prompt Template') }}</span>
                            <fv-combobox :theme="theme" v-model="promptTemplateModel"
                                :placeholder="appConfig.local('Select Prompt')" :options="allowedPrompts"
                                :choosen-slider-background="data?.borderColor"
                                :reveal-background-color="[data?.shadowColor, 'rgba(255, 255, 255, 1)']"
                                :reveal-border-color="data?.borderColor" border-radius="8"
                                style="width: 100%"></fv-combobox>
                            <span v-if="promptParamModel.length > 0" class="field-label">
                                {{ appConfig.local('Prompt Parameters') }}
                            </span>
                            <kv-input v-if="promptParamModel.length > 0" v-model="promptParamModel"
                                :readonly="true"></kv-input>
                        </div>

                        <div v-for="(item, index) in visibleInitParams" :key="`init_detail_${index}`"
                            class="parameter-field">
                            <span class="field-label">{{ item.name }}</span>
                            <value-input :theme="theme" v-model="item.value" :item-obj="item" :this-data="data" @update:modelValue="emits('edited')"
                                @mousedown.stop @click.stop></value-input>
                        </div>
                    </section>

                    <section class="parameter-section">
                        <div class="section-heading run">
                            <span>{{ appConfig.local('Run Parameters') }}</span>
                            <span class="count">{{ visibleRunParams.length }}</span>
                        </div>
                        <div v-for="(item, index) in visibleRunParams" :key="`run_detail_${index}`"
                            class="parameter-field">
                            <span class="field-label">{{ item.name }}</span>
                            <value-input :theme="theme" v-model="item.value" :item-obj="item" :this-data="data"
                                @update:modelValue="emitUpdateRunValue(item)" @mousedown.stop @click.stop></value-input>
                        </div>
                    </section>

                    <section v-if="currentLog" class="parameter-section execution-section">
                        <div class="section-heading execution">
                            <span>{{ appConfig.local('Execution Logs') }}</span>
                        </div>
                        <fv-progress-bar v-show="currentProgress > -1 && currentProgress < 100"
                            :model-value="currentProgress" :foreground="data?.borderColor"
                            style="width: 100%; margin: 5px 0px"></fv-progress-bar>
                        <div class="log-list">
                            <p v-for="(text, index) in currentLog" :key="index">{{ text }}</p>
                        </div>
                        <div v-show="isOverStep" class="execution-actions">
                            <fv-button theme="dark" icon="Diagnostic" :background="data?.borderColor"
                                border-radius="8" font-size="10" :is-box-shadow="true" style="width: 100%"
                                @click="showDetails">{{ appConfig.local('Show Details') }}</fv-button>
                            <fv-button theme="dark" icon="Download" :background="data?.borderColor"
                                border-radius="8" font-size="10" :is-box-shadow="true" style="width: 100%"
                                @click="downloadData">{{ appConfig.local('Download Data') }}</fv-button>
                        </div>
                    </section>
                </div>
        </div>
        <footer class="operator-detail-footer">
            <fv-button :theme="theme" border-radius="8" :is-box-shadow="true"
                style="width: 120px; margin-right: 8px" @click="close">
                {{ appConfig.local('Close') }}
            </fv-button>
        </footer>
    </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useAppConfig } from '@/stores/appConfig'
import { useDataflow } from '@/stores/dataflow'

import valueInput from '@/components/manage/mainFlow/nodes/operatorNode/valueInput/index.vue'
import PromptResourceInput from './PromptResourceInput.vue'
import kvInput from '@/components/manage/mainFlow/nodes/operatorNode/valueInput/kvInput.vue'

const props = defineProps({
    modelValue: { type: Boolean, default: false },
    nodeId: { type: String, default: '' },
    data: { type: Object, default: () => ({}) },
    theme: { type: String, default: 'light' }
})

const emits = defineEmits(['edited', 'update:modelValue', 'update-run-value', 'show-details', 'download-data'])
const appConfig = useAppConfig()
const dataflow = useDataflow()

const close = () => emits('update:modelValue', false)

const visibleInitParams = computed(() => (props.data?.operatorParams?.init || [])
    .filter((item) => item.show && !promptTemplateItems.value.includes(item)))
const visibleRunParams = computed(() => (props.data?.operatorParams?.run || [])
    .filter((item) => item.name !== 'storage' && !(props.data?.externalTemplate && ['question','answer'].includes(props.data.mmStepId) && item.name.startsWith('binding_'))))
const stepLabel = computed(() => props.data?.pipeline_idx ? `Step ${props.data.pipeline_idx}` : 'Operator')
const promptTemplateItems = computed(() => (props.data?.operatorParams?.init || []).filter(item => item.name === 'prompt_template' || item.name.endsWith('_prompt_template') || (props.data?.externalTemplate && ['question','answer'].includes(props.data.mmStepId) && item.name==='resource_ref')))
const promptTemplateItem = computed(() => (props.data?.operatorParams?.init || [])
    .find((item) => item.name === 'prompt_template'))
const isResourcePrompt = computed(() => !!promptTemplateItem.value?.value?.ref || String(promptTemplateItem.value?.value || '').startsWith('user_prompt:'))
const allowedPrompts = computed(() => (props.data?.allowed_prompts || []).map((item) => ({ key: item, text: item })))

const promptTemplateModel = computed({
    get() {
        const value = promptTemplateItem.value?.value
        if (!value) return {}
        const key = typeof value === 'object' ? value.cls_name : value
        return { key, text: key }
    },
    set(value) {
        if (!value?.key || value.key === promptTemplateModel.value.key || !promptTemplateItem.value) return
        emits('edited')
        const promptInfo = dataflow.promptInfo[value.key]
        const params = (promptInfo?.parameter?.init || []).map((param) => ({
            ...param,
            value: param.default_value || ''
        }))
        promptTemplateItem.value.value = { cls_name: value.key, params }
    }
})

const promptParamModel = computed({
    get() {
        const value = promptTemplateItem.value?.value
        return value && typeof value === 'object' ? (value.params || []) : []
    },
    set(value) {
        if (promptTemplateItem.value?.value && typeof promptTemplateItem.value.value === 'object') {
            promptTemplateItem.value.value.params = value
        }
    }
})

const currentLog = computed(() => {
    if (!dataflow.execution?.task_id) return null
    const key = `${props.data?.label}_${(props.data?.pipeline_idx || 1) - 1}`
    return dataflow.execution.operator_logs[key] || null
})
const currentProgress = computed(() => {
    if (!dataflow.execution?.task_id) return -1
    const key = `${props.data?.label}_${(props.data?.pipeline_idx || 1) - 1}`
    return dataflow.execution.operators_detail[key]?.progress_percentage ?? -1
})
const isOverStep = computed(() => {
    if (!dataflow.execution?.task_id) return false
    return dataflow.executionStep > ((props.data?.pipeline_idx || 1) - 1)
        || dataflow.execution.status === 'completed'
})

const emitUpdateRunValue = (item) => emits('update-run-value', { nodeId: props.nodeId, ...item })
const showDetails = () => emits('show-details', { pipeline_idx: props.data?.pipeline_idx })
const downloadData = () => emits('download-data', { pipeline_idx: props.data?.pipeline_idx })
</script>

<style lang="scss">
.operator-detail-drawer {
    position: fixed;
    top: 15px;
    right: 15px;
    bottom: 15px;
    width: min(420px, calc(100vw - 30px));
    padding: 14px;
    box-sizing: border-box;
    background: rgba(252, 252, 252, 0.96);
    border: 1px solid rgba(120, 120, 120, 0.16);
    border-radius: 8px;
    color: rgba(28, 30, 41, 1);
    display: flex;
    flex-direction: column;
    box-shadow: 0px 4px 20px rgba(0, 0, 0, 0.14);
    backdrop-filter: blur(14px);
    z-index: 30;

    &.dark {
        background: rgba(30, 30, 30, 0.96);
        color: rgba(245, 245, 245, 1);
    }

    .operator-detail-header {
        height: 42px;
        margin-bottom: 10px;
        padding-bottom: 8px;
        flex-shrink: 0;
        border-bottom: 1px solid rgba(120, 120, 120, 0.12);
        display: flex;
        align-items: center;
        justify-content: space-between;

        p {
            min-width: 0;
            font-size: 15px;
            font-weight: 700;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        button {
            width: 30px;
            height: 30px;
            flex-shrink: 0;
            color: inherit;
            background: rgba(120, 120, 120, 0.08);
            border: 0;
            border-radius: 8px;
            cursor: pointer;

            &:hover { background: rgba(120, 120, 120, 0.16); }
        }
    }

    .operator-detail-footer {
        padding-top: 10px;
        flex-shrink: 0;
        border-top: 1px solid rgba(120, 120, 120, 0.12);
        display: flex;
        justify-content: flex-end;
    }
}

.operator-detail-panel {
    min-height: 0;
    display: flex;
    flex: 1;
    flex-direction: column;

    .operator-detail-summary {
        padding: 12px;
        gap: 10px;
        background: rgba(120, 120, 120, 0.07);
        border: 1px solid rgba(120, 120, 120, 0.1);
        border-radius: 10px;
        display: flex;
        align-items: flex-start;

        .step-pill {
            padding: 3px 8px;
            flex-shrink: 0;
            color: rgba(69, 98, 213, 1);
            background: rgba(69, 98, 213, 0.1);
            border-radius: 999px;
            font-size: 10px;
            font-weight: 700;
        }

        .operator-name {
            font-size: 14px;
            font-weight: 700;
        }

        .operator-description {
            margin-top: 4px;
            color: rgba(120, 120, 120, 1);
            font-size: 12px;
            line-height: 1.6;
        }
    }

    .operator-detail-scroll {
        min-height: 0;
        margin-top: 10px;
        flex: 1;
        overflow-y: auto;
    }

    .parameter-section {
        margin-bottom: 14px;
        padding: 10px;
        background: rgba(120, 120, 120, 0.045);
        border: 1px solid rgba(120, 120, 120, 0.1);
        border-radius: 10px;

        .section-heading {
            margin-bottom: 8px;
            color: rgba(52, 199, 89, 1);
            font-size: 12px;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: space-between;

            &.run { color: rgba(0, 122, 255, 1); }
            &.execution { color: rgba(255, 149, 0, 1); }

            .count {
                min-width: 20px;
                padding: 2px 6px;
                background: rgba(120, 120, 120, 0.1);
                border-radius: 999px;
                color: rgba(120, 120, 120, 1);
                font-size: 12px;
                text-align: center;
            }
        }

        .parameter-field {
            margin-top: 9px;

            .field-label {
                margin-bottom: 4px;
                color: rgba(120, 120, 120, 1);
                font-size: 12px;
                font-weight: 600;
                display: block;
            }
        }
    }

    .log-list {
        max-height: 220px;
        padding: 8px;
        background: rgba(20, 20, 20, 1);
        border-radius: 6px;
        color: rgba(193, 252, 167, 1);
        font-size: 9px;
        overflow: auto;
    }

    .execution-actions {
        margin-top: 8px;
        gap: 6px;
        display: flex;
    }
}
</style>
