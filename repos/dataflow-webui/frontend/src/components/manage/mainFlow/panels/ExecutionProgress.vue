<template>
    <section v-if="taskId" class="execution-progress" :class="[{ dark: theme === 'dark' }, execution.status]" aria-label="运行进度">
        <header class="execution-summary">
            <button type="button" class="execution-toggle" :aria-expanded="expanded" @click="expanded = !expanded">
                <span class="status-dot" :class="execution.status"></span>
                <strong>{{ view.label }}</strong>
                <span v-if="view.total">已完成 {{ view.completed }} / {{ view.total }} 步</span>
                <span v-if="view.active" class="current-operator">{{ view.active.name }}</span>
                <span class="execution-elapsed">{{ elapsed }}</span>
                <span class="expand-label">{{ expanded ? '收起' : '展开' }} {{ expanded ? '⌄' : '⌃' }}</span>
            </button>
            <fv-button v-if="view.terminal" :theme="theme" :border-radius="6" @click="$emit('result')">{{ execution.status === 'completed' ? '查看结果' : '运行记录' }}</fv-button>
            <fv-button v-else :theme="theme" :border-radius="6" :disabled="stopping" @click="$emit('stop')">{{ stopping ? '正在停止…' : '停止' }}</fv-button>
        </header>
        <div v-if="expanded" class="execution-expanded">
            <div class="execution-info"><span>任务 {{ taskId }}</span><span v-if="execution.auto_collection?.status === 'collected'" class="collection-ok">已收录到生成数据集</span><span v-else-if="execution.status === 'completed'">收录与下载状态见最终结果</span></div>
            <p v-if="pollError" role="status" class="execution-warning">{{ pollError }} <button @click="$emit('refresh')">立即重试</button></p>
            <p v-if="view.error" class="execution-error" role="alert">{{ view.error }}</p>
            <div class="execution-body">
                <ol class="execution-steps">
                    <li v-for="step in view.steps" :key="step.key" :class="step.status">
                        <button type="button" @click="selectStep(step)">
                            <span class="step-number">{{ step.index + 1 }}</span>
                            <span class="step-name">{{ step.name }}</span>
                            <span class="step-state">{{ statusLabel(step.status) }}</span>
                        </button>
                        <div v-if="step.status === 'running'" class="step-progress">
                            <fv-progress-bar v-if="step.percentage !== null" :model-value="step.percentage" :foreground="color" style="width:100%" />
                            <div v-else class="indeterminate-line" aria-label="当前步骤正在执行，进度未报告"></div>
                            <span v-if="step.percentage !== null">当前步骤 {{ step.percentage }}%</span>
                            <span v-else>当前步骤执行中</span><span v-if="step.progress">{{ step.progress }}</span>
                        </div>
                        <p v-if="typeof step.sample_count === 'number'" class="step-output">输出 {{ step.sample_count }} 条</p>
                    </li>
                    <li v-if="!view.steps.length" class="step-output">等待执行器报告步骤状态…</li>
                </ol>
                <div class="execution-logs">
                    <div class="log-heading"><strong>{{ selectedStep?.name || '任务日志' }}</strong><button v-if="selectedStep" @click="selectedKey = ''">全部日志</button></div>
                    <pre v-if="visibleLogs.length">{{ visibleLogs.join('\n') }}</pre><p v-else>暂无日志</p>
                </div>
            </div>
        </div>
    </section>
</template>
<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { executionProgress, elapsedLabel, statusLabel } from '@/hooks/dataflow/executionProgress'
import { useTheme } from '@/stores/theme'
const props = defineProps({ taskId: String, execution: { type: Object, default: () => ({}) }, theme: String, pollError: String, stopping: Boolean })
const emit = defineEmits(['focus-step', 'result', 'stop', 'refresh', 'resize'])
const themeStore = useTheme()
const color = computed(() => themeStore.color)
const expanded = ref(false), selectedKey = ref(''), now = ref(Date.now())
const view = computed(() => executionProgress(props.execution))
const selectedStep = computed(() => view.value.steps.find(step => step.key === selectedKey.value))
const elapsed = computed(() => view.value.terminal && !props.execution.completed_at ? '用时未报告' : elapsedLabel(props.execution.started_at, props.execution.completed_at, now.value))
const visibleLogs = computed(() => (selectedStep.value ? props.execution.operator_logs?.[selectedKey.value] || [] : props.execution.logs || []).slice(-120))
function selectStep(step) { selectedKey.value = step.key; emit('focus-step', step) }
watch(expanded, async () => { await nextTick(); emit('resize') })
watch(() => props.taskId, () => { expanded.value = true; selectedKey.value = '' })
let clock
onMounted(() => { clock = setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => clearInterval(clock))
</script>
<style scoped>
.execution-progress{order:3;flex-shrink:0;--panel:#fafafa;--border:#e1e4ed;--text:#39465d;--muted:#78849a;--accent:#535fd6;background:var(--panel);color:var(--text);border-top:1px solid var(--border);font-size:12px}
.execution-progress.dark{--panel:#242424;--border:#3d414b;--text:#dce1ed;--muted:#a0a8b9;--accent:#b7c0ff}
.execution-summary{display:flex;align-items:center;gap:10px;padding:8px 12px}.execution-summary>.fv-button{min-width:82px;height:30px}
.execution-toggle{flex:1;min-width:0;display:flex;align-items:center;gap:12px;border:0;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;padding:6px 0}.execution-toggle strong{white-space:nowrap}.current-operator{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}.execution-elapsed{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums}.expand-label{white-space:nowrap;color:var(--muted)}
.status-dot{width:8px;height:8px;border-radius:50%;background:#a0a8b9;flex-shrink:0}.status-dot.running,.status-dot.initializing,.status-dot.queued,.status-dot.pending{background:#5965d8;animation:status-pulse 1.6s ease-in-out infinite}.status-dot.completed{background:#299668}.status-dot.failed{background:#d65663}.status-dot.cancelled{background:#ad8794}
.execution-expanded{padding:0 14px 14px}.execution-info{display:flex;justify-content:space-between;gap:12px;margin:4px 0 12px;color:var(--muted);overflow-wrap:anywhere}.collection-ok{color:#299668}.execution-body{display:grid;grid-template-columns:minmax(230px,2fr) minmax(240px,3fr);gap:14px;max-height:min(310px,40vh);overflow:auto}.execution-steps{padding:0;margin:0;list-style:none;overflow:auto}.execution-steps li{border-bottom:1px solid var(--border);padding:4px 0}.execution-steps li>button{width:100%;display:flex;align-items:center;gap:9px;padding:7px 4px;border:0;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}.execution-steps li>button:hover{background:color-mix(in srgb,var(--accent) 8%,transparent)}.step-number{width:20px;height:20px;display:grid;place-items:center;background:color-mix(in srgb,var(--muted) 12%,transparent);border-radius:5px;flex-shrink:0}.step-name{flex:1;overflow-wrap:anywhere}.step-state{white-space:nowrap;color:var(--muted)}.execution-steps li.completed .step-state{color:#299668}.execution-steps li.failed .step-state{color:#d65663}.execution-steps li.running .step-state{color:var(--accent)}.step-progress,.step-output{padding:3px 5px 8px 33px;color:var(--muted);font-size:11px}.step-progress span{display:block;margin-top:5px;overflow-wrap:anywhere}.indeterminate-line{height:3px;border-radius:3px;background:linear-gradient(90deg,transparent,var(--accent),transparent);background-size:200% 100%;animation:indeterminate 2s linear infinite}.execution-logs{min-width:0;overflow:auto;border:1px solid var(--border);border-radius:6px;padding:10px}.log-heading{display:flex;justify-content:space-between;gap:8px;margin-bottom:8px}.execution-logs pre{white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.7 ui-monospace,monospace;margin:0}.execution-logs p{color:var(--muted)}.log-heading button,.execution-warning button{border:0;background:transparent;color:var(--accent);font:inherit;cursor:pointer}.execution-error{color:#bd4454;line-height:1.7;margin:0 0 10px;overflow-wrap:anywhere}.execution-warning{color:#a16c29;line-height:1.7;margin:0 0 10px}
@keyframes status-pulse{50%{opacity:.35}}@keyframes indeterminate{to{background-position:-200% 0}}@media(prefers-reduced-motion:reduce){.status-dot,.indeterminate-line{animation:none}}@media(max-width:850px){.execution-body{grid-template-columns:1fr}.current-operator{display:none}.execution-toggle{gap:8px}.execution-info{flex-wrap:wrap}}
</style>
