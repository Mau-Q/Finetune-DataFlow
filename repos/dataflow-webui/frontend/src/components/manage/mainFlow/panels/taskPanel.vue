<template>
    <basePanel v-model="thisValue" :title="title" width="800px" height="80%" :theme="theme">
        <template v-slot:content>
            <div v-if="thisValue" class="panel-task-content-block">
                <div class="task-history-toolbar"><fv-button :theme="theme" :border-radius="6" :disabled="refreshing" @click="refreshTasks">{{ refreshing ? '刷新中…' : '刷新运行记录' }}</fv-button><span v-if="!filteredTasks.length">暂无运行记录</span></div>
                <TaskFinalResult v-if="selectedTaskId" :key="`${selectedTaskId}:${refreshRevision}`" :task-id="selectedTaskId" :theme="theme" @navigate="thisValue = false" />
                <fv-Collapse :theme="theme" v-for="(item, index) in filteredTasks" :key="index" class="task-item"
                    :title="item.task_id" :content="formatTime(item.completed_at)"
                    :maxHeight="item.showPreview ? 690 : 380" background="rgba(251, 251, 251, 1)"
                    :disabled-collapse="!item.resource_snapshots?.length">
                    <template v-slot:default>
                        <div v-for="snapshot in item.resource_snapshots || []" :key="`${snapshot.operator_index}-${snapshot.param_name}`" class="resource-snapshot">
                            <strong>步骤 {{ snapshot.operator_index + 1 }} · {{ snapshot.name }}</strong>
                            <p>{{ snapshot.ref }}</p>
                            <p>SHA-256：{{ snapshot.sha256 }}</p>
                            <pre>{{ JSON.stringify(snapshot.content, null, 2) }}</pre>
                        </div>
                    </template>
                    <template v-slot:icon>
                        <fv-img :src="img.task" style="width: auto; height: 30px; margin: 0px 5px"></fv-img>
                    </template>
                    <template v-slot:extension>
                        <span class="task-status" :class="item.status">{{ taskStatus(item.status) }}</span>
                        <fv-button :theme="theme" :border-radius="6" style="margin-right:8px" @click.stop="selectedTaskId = item.task_id">最终结果</fv-button>
                        <fv-button theme="dark" :icon="'View'"
                            :background="'linear-gradient(130deg, rgba(229, 123, 67, 1), rgba(225, 107, 56, 1))'"
                            :borderRadius="8" :isBoxShadow="true" @click="confirmView(item)">
                            <fv-progress-ring
                                v-show="item.status !== 'completed' && item.status !== 'failed' && item.status !== 'cancelled'"
                                loading="true" r="10" :border-width="2" background="rgba(255, 255, 255, 0.6)"
                                color="rgba(255, 255, 255, 1)"></fv-progress-ring>
                            查看流程
                        </fv-button>
                    </template>
                </fv-Collapse>
            </div>
        </template>
        <template v-slot:control="{ close }">
            <fv-button :theme="theme" :borderRadius="8" :isBoxShadow="true" style="width: 120px; margin-right: 8px"
                @click="close">{{
                    local('Close') }}</fv-button>
        </template>
    </basePanel>
</template>

<script>
import { mapState, mapActions } from 'pinia'
import { useAppConfig } from '@/stores/appConfig'
import { useDataflow } from '@/stores/dataflow'
import { useTheme } from '@/stores/theme'

import basePanel from '@/components/general/basePanel.vue'

import TaskFinalResult from './TaskFinalResult.vue'

import { statusLabel } from '@/hooks/dataflow/executionProgress'
import taskIcon from '@/assets/flow/task.svg'

export default {
    components: {
        basePanel,
        TaskFinalResult
    },
    props: {
        modelValue: {
            default: false
        },
        title: {
            default: 'task'
        },
        initialTaskId: { type: String, default: '' },
        currentPipeline: {
            default: null
        }
    },
    data() {
        return {
            thisValue: this.modelValue,
            selectedTaskId: this.initialTaskId,
            refreshing: false,
            refreshRevision: 0,
            img: {
                task: taskIcon
            }
        }
    },
    watch: {
        initialTaskId(val) { this.selectedTaskId = val },
        currentPipeline() { this.selectedTaskId = this.initialTaskId },
        modelValue(val) {
            this.thisValue = val
            if (val) {this.refreshRevision++;this.refreshTasks()}
        },
        thisValue(val) {
            this.$emit('update:modelValue', val)
        }
    },
    computed: {
        ...mapState(useAppConfig, ['local']),
        ...mapState(useDataflow, ['tasks']),
        ...mapState(useTheme, ['theme', 'color', 'gradient']),
        filteredTasks() {
            return this.tasks.filter((item) => !this.currentPipeline || item.pipeline_id === this.currentPipeline.id).slice().sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
        },
        formatTime() {
            return (dateStr) => {
                if (!dateStr) return '尚未结束'
                const date = new Date(dateStr)
                return Number.isFinite(date.getTime()) ? this.$SDate.Format('YYYY-mm-dd HH:MM:SS', date) : '时间未报告'
            }
        }
    },
    mounted() { },
    methods: {
        ...mapActions(useDataflow, ['getTasks']),
        taskStatus: statusLabel,
        async refreshTasks() {
            this.refreshing = true
            try { await this.getTasks() } finally { this.refreshing = false }
        },
        confirmView(item) {
            this.$emit('confirm', {
                task_id: item.task_id
            })
            this.thisValue = false
        }
    }
}
</script>

<style lang="scss">
.task-status{font-size:12px;margin-right:10px;color:#78849a}.task-status.completed{color:#299668}.task-status.failed{color:#d65663}.task-status.running{color:#5965d8}
.task-history-toolbar{display:flex;align-items:center;gap:12px;padding:8px}
.task-final-result{flex-shrink:0;}
.resource-snapshot { padding: 12px; font-size: 12px; overflow-wrap: anywhere; }
.resource-snapshot pre { max-height: 200px; overflow: auto; white-space: pre-wrap; }
.panel-task-content-block {
    position: relative;
    width: 100%;
    height: 100%;
    gap: 5px;
    display: flex;
    flex-direction: column;
    overflow: overlay;

    .task-item {
        flex-shrink: 0;

        .collapse-item-content {
            position: relative;
            height: auto;
            transition: all 0.3s;
        }
    }
}
</style>
