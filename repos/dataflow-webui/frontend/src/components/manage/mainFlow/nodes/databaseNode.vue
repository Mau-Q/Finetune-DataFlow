<template>
    <base-node v-bind="props" :data="displayData" :theme="theme">
        <div class="fv-loading-block">
            <fv-progress-ring
                v-if="loading"
                :loading="true"
                :r="18"
                :border-width="3"
                background="white"
                :color="thisData.borderColor"
            ></fv-progress-ring>
        </div>
        <div v-if="!showFields" class="dataset-compact-summary" @mousedown.stop>
            <div class="dataset-stat">
                <strong>{{ thisData.num_samples }}</strong>
                <span>{{ appConfig.local('Samples') }}</span>
            </div>
            <div class="dataset-actions">
                <button class="dataset-action secondary nodrag" type="button" @click.stop="showFields = true">
                    <i class="ms-Icon ms-Icon--Table"></i>
                    {{ fieldCount }} {{ appConfig.local('Fields') }}
                </button>
                <button class="dataset-action primary nodrag" type="button"
                    @click.stop="$emit('switch-database', thisData)">
                    <i class="ms-Icon ms-Icon--Switch"></i>
                    {{ appConfig.local('Switch') }}
                </button>
            </div>
        </div>
        <div v-else class="node-group-item dataset-expanded" @mousedown.stop @click.stop @wheel.stop>
            <div class="fields-header">
                <span>{{ appConfig.local('Dataset Details') }}</span>
                <button type="button" :title="appConfig.local('Hide fields')" @click.stop="showFields = false">
                    <i class="ms-Icon ms-Icon--ChevronUp"></i>
                </button>
            </div>
            <div class="node-row-item">
                <span class="info-title">{{ appConfig.local('ID') }}</span>
                <p class="info-value tiny" :title="thisData.id">{{ thisData.id }}</p>
            </div>
            <div class="node-row-item">
                <span class="info-title">{{ appConfig.local('Root') }}</span>
                <p class="info-value tiny" :title="thisData.root">{{ thisData.root }}</p>
            </div>
            <div class="node-row-item">
                <span class="info-title">{{ appConfig.local('Hash') }}</span>
                <p class="info-value tiny" :title="thisData.hash">{{ thisData.hash }}</p>
            </div>
            <hr style="margin: 10px 8px" />
            <template v-if="thisData.operatorParams">
                <div v-for="(item, index) in thisData.operatorParams.run" :key="`run_${index}`"
                    class="node-row-item col">
                    <Handle :id="`${item.name}::source::run_key`" type="source" class="handle-item"
                        :position="Position.Right" style="margin-right: -15px" />
                    <fv-text-box v-model="item.value"
                        :placeholder="appConfig.local('Please input') + ` ${item.name}`" font-size="12"
                        border-radius="8" :reveal-border="true" readonly @mousedown.stop @click.stop
                        style="width: 100%; height: 35px; margin-top: 5px"></fv-text-box>
                </div>
            </template>
            <div class="node-row-item">
                <button class="dataset-action primary full" type="button" :disabled="loading"
                    @click.stop="$emit('switch-database', thisData)">
                    {{ appConfig.local('Switch Dataset') }}
                </button>
            </div>
        </div>
    </base-node>
</template>

<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import { useAppConfig } from '@/stores/appConfig'
import { useTheme } from '@/stores/theme'
import { useGlobal } from '@/hooks/general/useGlobal'
import { Position, Handle } from '@vue-flow/core'

import baseNode from '@/components/manage/mainFlow/nodes/baseNode.vue'

import databaseIcon from '@/assets/flow/database.svg'

const { $api } = useGlobal()

const emits = defineEmits(['switch-database', 'update-node-data'])

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

const defaultData = {
    label: 'Dataset',
    status: 'Dataset',
    nodeInfo: 'This is a Dataset node.',
    img: databaseIcon,
    background: 'linear-gradient(130deg, rgba(161, 145, 206, 0.8), rgba(252, 252, 252, 0.8))',
    titleColor: '',
    statusColor: 'rgba(90, 90, 90, 1)',
    infoTitleColor: 'rgba(90, 90, 90, 1)',
    borderColor: 'rgba(177, 146, 247, 1)',
    shadowColor: '',
    groupBackground: 'rgba(255, 255, 255, 0.8)',
    useTargetHandle: false,
    enableDelete: true,
    defaultSourceHandleTop: '50px'
}
const thisData = computed(() => {
    return {
        ...defaultData,
        ...props.data
    }
})

const appConfig = useAppConfig()
const themeStore = useTheme()
const theme = computed(() => themeStore.theme)

const loading = ref(false)
const showFields = ref(false)
const fieldCount = computed(() => thisData.value.operatorParams?.run?.length || 0)
const displayData = computed(() => ({
    ...thisData.value,
    nodeInfo: thisData.value.pipelineRole
        || `提供 ${thisData.value.num_samples || 0} 条数据，作为这条 Pipeline 的原始输入。`,
    background: theme.value === 'dark' ? 'rgba(35, 35, 38, 0.96)' : 'rgba(255, 255, 255, 0.96)',
    titleColor: theme.value === 'dark' ? 'rgba(255, 255, 255, 0.96)' : 'rgba(43, 46, 56, 1)',
    statusColor: theme.value === 'dark' ? 'rgba(215, 215, 220, 0.92)' : 'rgba(82, 86, 98, 1)',
    infoTitleColor: theme.value === 'dark' ? 'rgba(215, 215, 220, 0.92)' : 'rgba(82, 86, 98, 1)',
    compact: !showFields.value
}))
const getNodeDetail = async () => {
    if (props.data.externalTemplate) return
    if (!props.data || !props.data.name) return
    loading.value = true
    const res = await $api.datasets.get_dataset_columns(props.data.id).catch(() => {
        loading.value = false
    })
    loading.value = false
    if (res.code === 200) {
        let keys = res.data
        let runPrams = []
        keys.forEach((item) => {
            runPrams.push({
                name: item,
                value: item,
                default_value: item
            })
        })
        let operatorParams = {
            init: [],
            run: []
        }
        operatorParams.run = runPrams
        emits('update-node-data', {
            id: props.id,
            data: {
                ...props.data,
                operatorParams
            }
        })
    }
}

watch(
    () => props.data.id,
    () => {
        getNodeDetail()
    }
)

onMounted(() => {
    getNodeDetail()
})
</script>

<style lang="scss">
.df-flow-default-node {
    .dataset-compact-summary {
        width: calc(100% - 20px);
        height: 100%;
        margin: 0 10px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;

        .dataset-stat {
            display: flex;
            flex-direction: column;

            strong {
                color: var(--node-title-color);
                font-size: 18px;
                line-height: 1;
            }

            span {
                margin-top: 4px;
                color: var(--node-status-color);
                font-size: 10px;
            }
        }

        .dataset-actions {
            display: flex;
            gap: 6px;
        }
    }

    .dataset-action {
        height: 28px;
        padding: 0 9px;
        border-radius: 7px;
        font-size: 10px;
        font-weight: 700;
        cursor: pointer;

        i {
            margin-right: 3px;
        }

        &.primary {
            color: #fff;
            background: var(--node-border-color);
            border: 1px solid var(--node-border-color);
        }

        &.secondary {
            color: var(--node-title-color);
            background: var(--node-group-background);
            border: 1px solid var(--node-border-color);
        }

        &.full {
            width: 100%;
            margin-top: 12px;
        }

        &:hover {
            filter: brightness(1.12);
        }
    }

    .dataset-expanded {
        max-height: 430px;
        overflow-y: auto;

        .fields-header {
            min-height: 30px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            color: var(--node-status-color);
            font-size: 10px;
            font-weight: 700;

            button {
                width: 26px;
                height: 26px;
                color: var(--node-title-color);
                background: transparent;
                border: 0;
                border-radius: 6px;
                cursor: pointer;
            }
        }
    }
}
</style>
