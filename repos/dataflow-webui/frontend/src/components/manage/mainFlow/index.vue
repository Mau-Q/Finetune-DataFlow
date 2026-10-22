<template>
    <div class="df-main-flow-container">
        <VueFlow class="main-flow" :id="id" v-model:nodes="thisNodes" v-model:edges="thisEdges" @dragover="dragOver"
            @drop="drop" @dragleave="dragLeave" @connect="$emit('edited');$emit('connect', $event)"
            @move-end="$emit('viewport-change')" @node-drag-stop="$emit('edited')" @edges-change="changes => {if(changes.some(c=>c.type==='remove'))$emit('edited')}"
            @connect-end="$emit('connect-end', $event)" @connect-start="$emit('connect-start', $event)"
            @node-click="selectOperator" @nodes-initialized="$emit('nodes-ready')">
            <Background variant="dots" gap="20" size="3" :color="'rgba(200, 200, 200, 0.3)'" :style="{
                backgroundColor: isDragOver ? 'rgba(87, 99, 206, 0.05)' : 'transparent',
                transition: 'background-color 0.2s ease'
            }"></Background>
            <template #node-base-node="nodeProps">
                <baseNode v-bind="nodeProps" @delete-node="deleteNode" />
            </template>
            <template #node-database-node="nodeProps">
                <databaseNode v-bind="nodeProps" @delete-node="deleteNode" @switch-database="switchDatabase"
                    @update-node-data="updateNodeData" />
            </template>
            <template #node-operator-node="nodeProps">
                <operatorNode v-bind="nodeProps" @delete-node="deleteNode" @update-node-data="updateNodeData"
                    @update-run-value="updateRunValue" @show-details="showDetails" @download-data="downloadData" @inspect-node="inspectOperator" />
            </template>

            <template #connection-line="connectionLineProps">
                <baseConnectionLine v-bind="connectionLineProps"></baseConnectionLine>
            </template>
            <template #edge-base-edge="edgeProps">
                <baseEdge v-bind="edgeProps" />
            </template>
        </VueFlow>
        <slot v-if="!thisNodes.length" name="empty" />
        <Teleport to="body">
            <operator-detail-panel @edited="emits('edited')" v-if="selectedOperator" :key="selectedOperator.id" v-model="showInspector"
                :node-id="selectedOperator.id" :data="selectedOperator.data" :theme="theme"
                @update-run-value="updateRunValue" @show-details="showDetails" @download-data="downloadData" />
        </Teleport>
    </div>
</template>

<script setup>
import { ref, watch, computed, onDeactivated, nextTick } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { useGlobal } from '@/hooks/general/useGlobal'
import { useTheme } from '@/stores/theme'
import { useAppConfig } from '@/stores/appConfig'
import { Background } from '@vue-flow/background'
import baseNode from './nodes/baseNode.vue'
import baseEdge from './edges/baseEdge.vue'
import databaseNode from './nodes/databaseNode.vue'
import operatorNode from './nodes/operatorNode/index.vue'
import operatorDetailPanel from './panels/operatorDetailPanel.vue'
import baseConnectionLine from './edges/baseConnectionLine.vue'

defineOptions({ name: 'DataflowCanvas' })

const { $Guid, $infoBox } = useGlobal()
const appConfig = useAppConfig()
const _theme = useTheme()
const theme = computed(() => _theme.theme)
const emits = defineEmits([
    'edited',
    'viewport-change',
    'switch-database',
    'nodes-ready',
    'update:nodes',
    'update:edges',
    'connect',
    'connect-end',
    'connect-start',
    'update-run-value',
    'show-details',
    'download-data'
])

const props = defineProps({
    id: {
        type: String,
        required: true
    },
    nodes: {
        type: Array,
        default: () => []
    },
    edges: {
        type: Array,
        default: () => []
    }
})

const canvasFlow = useVueFlow(props.id)
const thisNodes = ref(props.nodes)
const thisEdges = ref(props.edges)
const selectedOperatorId = ref(null)
const selectedOperator = computed(() => canvasFlow.findNode(selectedOperatorId.value) || thisNodes.value.find(n => n.id === selectedOperatorId.value) || null)
const showInspector = ref(false)
watch(
    () => props.nodes,
    (newNodes) => {
        thisNodes.value = newNodes
        if (selectedOperatorId.value && !newNodes.some(n => n.id === selectedOperatorId.value) && !canvasFlow.findNode(selectedOperatorId.value)) { selectedOperatorId.value = null; closeInspector() }
    }
)
watch(
    () => props.edges,
    (newEdges) => {
        thisEdges.value = newEdges
    }
)
watch(
    () => thisNodes.value,
    (newNodes) => {
        emits('update:nodes', newNodes)
    }
)
watch(
    () => thisEdges.value,
    (newEdges) => {
        emits('update:edges', newEdges)
    }
)

const switchDatabase = (dataset) => {
    emits('switch-database', dataset)
}

const updateNodeData = (nodeInfo) => {
    const flow = useVueFlow(props.id)
    const existsNode = flow.findNode(nodeInfo.id)
    if (existsNode) {
        flow.updateNodeData(existsNode.id, nodeInfo.data)
    }
}

const updateRunValue = (runValue) => {
    emits('edited')
    emits('update-run-value', runValue)
}

const selectOperator = ({ node }) => {
    if (!node || node.type !== 'operator-node') {
        closeInspector()
        return
    }
    selectedOperatorId.value = node.id
    showInspector.value = true
}

const inspectOperator = (nodeId) => {
    selectOperator({ node: canvasFlow.findNode(nodeId) || thisNodes.value.find(n => n.id === nodeId) })
}

const closeInspector = () => {
    showInspector.value = false
}

onDeactivated(closeInspector)

const isDragOver = ref(false)
const dragOver = (event) => {
    event.preventDefault()
    isDragOver.value = true
}
const addOperator = async (data, position = null) => {
    const existing = canvasFlow.nodes.value || thisNodes.value
    const last = existing.at(-1)
    const node = {
        id: $Guid(), type: 'operator-node',
        position: position || { x: last ? last.position.x + 320 : 280, y: last?.position.y || 160 },
        data: { ...JSON.parse(JSON.stringify(data)), flowId: props.id, enableDelete: true }
    }
    canvasFlow.addNodes(node)
    emits('edited')
    await nextTick()
    if (!position) inspectOperator(node.id)
    return node.id
}
const drop = (event) => {
    event.preventDefault()
    const raw = event.dataTransfer.getData('application/vueflow')
    if (!raw) return
    try {
        const position = canvasFlow.screenToFlowCoordinate({ x: event.clientX - Number(event.dataTransfer.getData('event/offsetX') || 0), y: event.clientY - 30 })
        addOperator(JSON.parse(raw), position)
    } finally { isDragOver.value = false }
}
defineExpose({ addOperator, inspectOperator, closeInspector })
const dragLeave = (event) => {
    event.preventDefault()
    isDragOver.value = false
}

const deleteNode = (nodeInfo) => {
    $infoBox(appConfig.local(`Are you sure to delete this node?`), {
        status: 'error',
        theme: theme.value,
        confirm: () => {
            const flow = useVueFlow(props.id)
            flow.removeNodes(nodeInfo.id)
            emits('edited')
            if (selectedOperator.value?.id === nodeInfo.id) {
                selectedOperatorId.value = null
                showInspector.value = false
            }
        }
    })
}

const showDetails = ({ pipeline_idx }) => {
    emits('show-details', pipeline_idx)
}
const downloadData = ({ pipeline_idx }) => {
    emits('download-data', pipeline_idx)
}
</script>

<style lang="scss">
/* import the necessary styles for Vue Flow to work */
@import '@vue-flow/core/dist/style.css';

/* import the default theme, this is optional but generally recommended */
@import '@vue-flow/core/dist/theme-default.css';

.df-main-flow-container {
    position: relative;
    width: 100%;
    height: 100%;
}
</style>
