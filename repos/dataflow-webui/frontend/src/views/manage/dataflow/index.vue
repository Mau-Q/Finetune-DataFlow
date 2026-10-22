<template>
    <router-link v-if="isMM" :to="{path:'/m/multimodal',query:{config:mmRecord?.id}}" class="wizard-return">图片、服务与输出设置 · MM 未启用运行</router-link>
    <div class="df-default-container" :class="[{ dark: theme === 'dark', 'show-pipeline': show.pipeline }]">
        <pipeline v-model="show.pipeline" v-model:loading="lock.loading" v-model:pipeline="currentPipeline"
            :before-change="confirmCanvasChange" :flow-id="flowId" class="df-pipeline-container" @confirm-dataset="confirmDataset($event, true)"
            @select-pipeline="selectPipelineCallback"></pipeline>
        <div class="df-flow-container">
            <mainFlow ref="canvas" @viewport-change="scheduleWorkspaceSave" @edited="markCanvasEdited" :id="flowId" v-model:nodes="nodes" v-model:edges="edges" @switch-database="openInputSettings"
                @connect="onConnect" @connect-start="onConnectStart" @connect-end="onConnectEnd"
                @update-run-value="useEdgeSync.syncRunValue($event, flowId)" @show-details="showExecDetails"
                @download-data="downloadData" @nodes-ready="fitPlatformWhenReady" @click="show.pipeline = false">
                <template #empty>
                    <div class="canvas-empty-state" @click.stop>
                        <i class="ms-Icon ms-Icon--Flow" aria-hidden="true"></i>
                        <h2>开始一个数据生成流程</h2>
                        <p>选择已有 Pipeline 或模板，再添加输入数据与算子。</p>
                        <fv-button class="canvas-start-button" :theme="theme" border-radius="6" icon="OpenFolderHorizontal" style="width: 150px; height: 34px"
                            @click.stop="show.pipeline = true">选择 Pipeline</fv-button>
                    </div>
                </template>
            </mainFlow>
            <div class="control-menu-block" role="toolbar" aria-label="Pipeline 操作">
                <current-pipeline-block v-model="currentPipeline" :taskId="executionInfo.task_id"
                    @recover-click="recoverPipeline"></current-pipeline-block>
                <fv-command-bar :theme="theme" v-model="value" :options="options" :item-border-radius="6"
                    :background="theme === 'dark' ? '' : 'rgba(250, 250, 250, 0.8)'" class="command-bar">
                    <template v-slot:optionItem="x">
                        <div class="command-bar-item-wrapper">
                            <fv-img v-if="x.item.img" class="option-img" :src="x.item.img" alt="" />
                            <i v-else class="ms-Icon icon" :class="[`ms-Icon--${x.valueTrigger(x.item.icon)}`]"
                                :style="{ color: x.valueTrigger(x.item.foreground) }"></i>
                            <p class="option-name" :style="{ color: x.valueTrigger(x.item.foreground) }">
                                {{ x.valueTrigger(x.item.name) }}
                            </p>
                            <i v-show="x.item.secondary.length > 0" class="ms-Icon ms-Icon--ChevronDown icon"></i>
                        </div>
                    </template>
                </fv-command-bar>
                <div class="command-bar-right-space" role="group" aria-label="画布与运行">
                    <fv-toggle-switch v-if="!isMM" :theme="theme" v-model="isAutoConnectionModel" :width="115"
                        :on="local('Auto Connect')" :off="local('Manual Connect')" :insideContent="true" :height="30"
                        :off-foreground="theme === 'dark' ? 'rgba(255, 255, 255, 1)' : ''"
                        borderColor="rgba(235, 235, 235, 1)" ring-background="rgba(180, 180, 180, 1)"
                        :switch-on-background="gradient" :title="local('Whether Auto Connect Run Edges')">
                    </fv-toggle-switch>
                    <fv-button :theme="theme" border-radius="6" :title="local('Auto Layout')"
                        style="width: 96px; height: 30px" @click="markCanvasEdited();autoLayoutPipeline()">
                        <i class="ms-Icon ms-Icon--GridViewMedium" style="margin-right: 5px"></i>
                        <p>{{ local('Auto Layout') }}</p>
                    </fv-button>
                    <fv-button v-if="!isMM" :theme="currentServing ? 'dark' : theme" :background="currentServing
                        ? 'rgba(69, 98, 213, 1)'
                        : ''
                        " border-radius="6" :disabled="!lock.serving" style="width: 30px; height: 30px"
                        @click="showServing">
                        <transition-group tag="span" name="df-scale-up-to-up">
                            <i v-show="currentServing" key="0" class="ms-Icon"
                                :class="[`ms-Icon--DialShape4`]"></i>
                            <i v-show="!currentServing" key="1" class="ms-Icon" :class="[`ms-Icon--More`]"></i>
                        </transition-group>
                        <i v-show="false" class="ms-Icon"
                            :class="[`ms-Icon--${currentServing ? 'DialShape4' : 'More'}`]"></i>
                    </fv-button>
                    <fv-button :theme="theme" border-radius="6" style="width:86px;height:30px" @click="inspectPreflight">检查配置</fv-button>
                    <fv-button theme="dark"
                        background="rgba(69, 98, 213, 1)"
                        foreground="rgba(255, 255, 255, 1)" border-color="rgba(255, 255, 255, 0.3)"
                        border-radius="6" :disabled="(!currentPipeline && !nodes.some(n => n.type === 'operator-node')) || runPreparing || !lock.running" :reveal-background-color="[
                            'rgba(255, 255, 255, 0.5)',
                            'rgba(103, 105, 251, 0.6)'
                        ]" style="width: 120px;" @click="openRunConfirm">
                        <i v-show="lock.running" class="ms-Icon ms-Icon--Play" style="margin-right: 5px"></i>
                        <fv-progress-ring v-show="!lock.running" loading="true" :r="10" :border-width="2"
                            background="rgba(200, 200, 200, 1)" :color="'white'"
                            style="margin-right: 5px"></fv-progress-ring>
                        <p>{{ this.local('Save & Run') }}</p>
                    </fv-button>
                    <fv-button v-show="!lock.running && executionInfo.task_id" theme="dark"
                        background="rgba(200, 38, 95, 0.9)" font-size="10" foreground="rgba(255, 255, 255, 1)"
                        border-color="whitesmoke" border-radius="6" :title="local('Stop')"
                        style="width: 30px; height: 30px" @click="stopExecution">
                        <i class="ms-Icon ms-Icon--StopSolid"></i>
                    </fv-button>
                    <fv-button :theme="theme"
                        foreground="rgba(185, 65, 75, 1)" border-radius="6"
                        :title="local('Delete')" style="width: 30px; height: 30px" @click="resetFlow">
                        <i class="ms-Icon ms-Icon--Delete"></i>
                    </fv-button>

                </div>
            </div>
            <section v-if="showPreflight" class="canvas-preflight" :class="{ dark: theme === 'dark' }" aria-label="运行前检查">
                <header><strong>{{ preflightIssues.length ? `需要处理 ${preflightIssues.length} 项配置` : '配置检查通过' }}</strong><button @click="showPreflight = false" aria-label="关闭配置检查">×</button></header>
                <p v-if="!preflightIssues.length">输入、节点连接与已知必填参数检查通过，运行时仍由后端校验。</p>
                <button v-for="(issue,index) in preflightIssues" :key="index" class="preflight-issue" @click="focusIssue(issue)"><span>{{ issue.name }}</span>{{ issue.message }} →</button>
            </section>
            <ExecutionProgress v-if="executionInfo.task_id" :task-id="executionInfo.task_id" :execution="currentExecution" :theme="theme" :poll-error="pollError" :stopping="stopping"
                @resize="fitExecutionView" @focus-step="focusExecutionStep" @result="openExecutionResult" @stop="stopExecution" @refresh="refreshExecution" />
        </div>
        <page-loading :model-value="!lock.loading" title="Loading..."></page-loading>
        <datasetPanel v-model="show.dataset" :title="local('原始数据集')" @confirm="confirmDataset"></datasetPanel>
        <operatorPanel v-model="show.operator" :title="local('Operator')" @add="addOperator"></operatorPanel>
        <fv-right-menu :theme="theme" v-model="show.serving" class="serving-menu" ref="servingMenu"
            :rightMenuWidth="250" :background="theme === 'dark' ? 'rgba(30, 30, 30, 1)' : 'rgba(255, 255, 255, 0.3)'"
            :fullExpandAnimation="true" style="z-index: 6">
            <p style="
                    width: calc(100% - 20px);
                    margin: 10px;
                    font-size: 12px;
                    font-weight: bold;
                    user-select: none;
                    cursor: default;
                ">
                {{ local('Select Serving') }}
            </p>
            <hr />
            <span class="serving-item" :class="{ choosen: currentServing && currentServing.id === servingItem.id }"
                v-for="servingItem in servingList" :key="servingItem.id" @click="chooseServing(servingItem)">
                <p class="main-title">{{ servingItem.name }}</p>
                <p class="sec-title">{{ servingItem.cls_name }}</p>
            </span>
            <hr />
            <fv-button :theme="theme" :icon="servingList.length > 0 ? '' : 'Add'" border-radius="8"
                style="width: calc(100% - 20px); margin-left: 10px; margin-top: 5px"
                @click="$Go('/m/serving'), (show.serving = false)">{{
                    servingList.length > 0 ? local('Serving Manage') : local('Add Serving')
                }}</fv-button>
        </fv-right-menu>
        <pipelinePanel v-model="show.pipelinePanel" :add-panel-mode="'custom'" :title="local('Pipeline')"
            @confirm="addPipeline"></pipelinePanel>
        <execResultPanel v-model="show.execResult" :title="local('Execute Result')" :current-pipeline="currentPipeline"
            :current-step="executionInfo.currentStep" :running-result="executionInfo.runningResult"></execResultPanel>
        <run-confirm-panel v-model="show.runConfirm" :theme="theme" :pipeline-name="currentPipeline?.name || 'Pipeline'" :dataset-name="sourceDatabase?.name || ''" :contract="runCollectionContract" @confirm="handleRunClick" />
        <taskPanel v-model="show.taskPanel" :title="local('运行记录')" :current-pipeline="currentPipeline" :initial-task-id="historyTaskId"
            @confirm="handleWatchExecution"></taskPanel>
    </div>
</template>

<script>
import { useUnsavedChanges, confirmDiscard } from '@/components/manage/forms/unsaved'
import { mapState, mapActions } from 'pinia'
import { useAppConfig } from '@/stores/appConfig'
import { useTheme } from '@/stores/theme'
import { useDataflow } from '@/stores/dataflow'
import { useVueFlow } from '@vue-flow/core'
import { useEdgeSync } from '@/hooks/dataflow/useEdgeSync'
import { usePipelineOperation } from '@/hooks/dataflow/usePipelineOperation'
import { nativeMMGraph, readNativeMM } from '@/hooks/dataflow/nativeMM'
import { buildSnakeLayout } from '@/hooks/dataflow/useAutoLayout'
import { checkPipeline } from '@/hooks/dataflow/preflight'
import { readWorkspaceState, writeWorkspaceState } from '@/hooks/dataflow/workspaceState'
import { terminalStatuses } from '@/hooks/dataflow/executionProgress'
import ExecutionProgress from '@/components/manage/mainFlow/panels/ExecutionProgress.vue'

import mainFlow from '@/components/manage/mainFlow/index.vue'
import pipeline from '@/components/manage/mainFlow/pipeline/index.vue'
import pipelinePanel from '@/components/manage/mainFlow/panels/piplinePanel.vue'
import datasetPanel from '@/components/manage/mainFlow/panels/datasetPanel/index.vue'
import operatorPanel from '@/components/manage/mainFlow/panels/operatorPanel.vue'
import pageLoading from '@/components/general/pageLoading.vue'
import currentPipelineBlock from '@/components/manage/mainFlow/tools/currentPipelineBlock.vue'
import execResultPanel from '@/components/manage/mainFlow/panels/execResultPanel/index.vue'
import runConfirmPanel from '@/components/manage/mainFlow/panels/runConfirmPanel.vue'
import taskPanel from '@/components/manage/mainFlow/panels/taskPanel.vue'

import databaseIcon from '@/assets/flow/database.svg'
import pipelineIcon from '@/assets/flow/pipeline.svg'
import operatorIcon from '@/assets/flow/operator.svg'
import taskIcon from '@/assets/flow/task.svg'
import saveIcon from '@/assets/flow/save.svg'

import axios from '@/axios/config'
import http from 'axios'

export default {
    setup(){
        const state=useVueFlow('df-main-flow')
        useUnsavedChanges(vm=>vm.canvasDirty && !vm.persistWorkspace(),vm=>{vm.canvasBaseline='';vm.canvasEdited=false})
        return {canvasNodes:()=>state.nodes.value,canvasEdges:()=>state.edges.value}
    },
    name: "dataflowPage",
    components: {
        mainFlow,
        ExecutionProgress,
        pipeline,
        pipelinePanel,
        datasetPanel,
        operatorPanel,
        pageLoading,
        currentPipelineBlock,
        execResultPanel,
        taskPanel,
        runConfirmPanel
    },
    data() {
        return {
            flowId: 'df-main-flow', canvasBaseline:'', canvasEdited:false,
            showPreflight:false, preflightLoading:false, pollError:'', stopping:false, uiSaveTimer:null, workspaceRestoring:false, viewportRestored:false, workspaceNotice:'',
            historyTaskId: '',
            mmRecord: null,
            platformFitKey: '',
            value: null,
            options: [
                {
                    name: () => this.local('原始数据集'),
                    icon: 'Play',
                    img: databaseIcon,
                    func: () => {
                        this.openInputSettings()
                    }
                },
                {
                    name: () => this.local('Pipeline'),
                    img: pipelineIcon,
                    func: () => {
                        this.show.pipeline ^= true
                    }
                },
                {
                    name: () => this.local('Operator'),
                    img: operatorIcon,
                    show: () => !this.isMM,
                    func: () => {
                        if (!this.isMM) this.show.operator = true
                    }
                },
                {
                    name: () => this.local('Execution'),
                    img: taskIcon,
                    show: () => {
                        return this.relatedTasks.length > 0
                    },
                    func: () => {
                        this.show.taskPanel = true
                    }
                },
                {
                    name: () => this.local('Save'),
                    img: saveIcon,
                    func: () => {
                        this.handleSaveClick()
                    }
                }
            ],
            nodes: [
                // {
                //     id: '1',
                //     type: 'base-node',
                //     position: { x: 70, y: 160 },
                //     data: {
                //         label: 'Node 1',
                //         nodeInfo:
                //             'Node Info: This is node info block for displaying node information.',
                //         iconColor: 'rgba(0, 108, 126, 1)'
                //     }
                // }
            ],

            edges: [],
            sourceDatabase: null,
            currentPipeline: null,
            pendingRun: false,
            runPreparing: false,
            executionInfo: {
                task_id: null,
                currentStep: null,
                runningResult: null,
            },
            timer: {
                exec: null
            },
            useEdgeSync: new useEdgeSync(),
            show: {
                dataset: false,
                pipeline: false,
                pipelinePanel: false,
                operator: false,
                serving: false,
                execResult: false,
                taskPanel: false,
                runConfirm: false,
            },
            lock: {
                serving: true,
                running: true,
                loading: true
            },
            // 聊天面板宽度（可拖拽调整，跨刷新持久化）
        }
    },
    watch: {
        preflightIssues() { this.syncValidationErrors() },
        showPreflight() { this.syncValidationErrors() },
        canvasFingerprint() { this.scheduleWorkspaceSave() },
        'executionInfo.task_id'() { this.scheduleWorkspaceSave() },
        'show.pipelinePanel'(visible) { if (!visible) this.pendingRun = false },
        $route(to, from) {
            if (to.path.replace(/\/$/, '') !== '/m') return
            if (to.query.task && to.query.task !== from.query.task) this.openTaskHistory(to.query.task)
            if (to.query.workflow && to.fullPath !== from.fullPath) this.loadPlatformWorkflow()
            else if (!to.query.workflow && to.query.pipeline && (from.path !== to.path || from.query.pipeline !== to.query.pipeline)) this.loadLinkedPipeline(to.query.pipeline)
        },
        sourceDatabase: {
            handler(newVal, oldVal) {
                if (newVal !== oldVal && !this.workspaceRestoring) {
                    this.updateDatabaseNode()
                }
            },
            deep: true
        },
        currentPipeline() {
            this.getTasks()
            if (!this.workspaceRestoring) { clearInterval(this.timer.exec); this.executionInfo.task_id = null; this.clearExecution(); this.lock.running = true }
        },
        isAutoConnection(val) {
            if (val) {
                this.useEdgeSync.autoConnectAllRunEdges(this.flowId, this.$Guid)
            }
        },

    },
    computed: {
        currentExecution() { return this.execution.task_id === this.executionInfo.task_id ? this.execution : {} },
        preflightIssues() { return checkPipeline(this.canvasNodes(), this.canvasEdges(), this.sourceDatabase) },
        canvasFingerprint(){
            const nodes=this.canvasNodes(),edges=this.canvasEdges()
            return JSON.stringify([this.sourceDatabase?.id,nodes.map(n=>({id:n.id,type:n.type,position:{x:n.position.x,y:n.position.y},params:Object.fromEntries(['init','run'].map(kind=>[kind,(n.data?.operatorParams?.[kind] || []).map(p=>({name:p.name,value:p.value}))]))})).sort((a,b)=>a.id.localeCompare(b.id)),edges.map(e=>({source:e.source,target:e.target,sourceHandle:e.sourceHandle,targetHandle:e.targetHandle})).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)))])
        },
        canvasDirty(){return this.canvasEdited && !!this.canvasBaseline && this.canvasBaseline!==this.canvasFingerprint},
        runCollectionContract() {
            const c = this.currentPipeline?.config
            if(c?.execution_options?.simple_training)return c.execution_options.simple_training
            const names=(c?.operators || []).map(op => op.name)
            const kind=names.some(n => /DPO/.test(n)) ? 'dpo' : names.some(n => /SFT/.test(n)) ? 'sft' : null
            return kind ? {modality:names.some(n => /Image|VQA/.test(n))?'image_text':'text',training_type:kind} : null
        },
        isMM() { return this.$route.query.workflow === 'multimodal' },
        ...mapState(useAppConfig, ['local']),
        ...mapState(useTheme, ['theme', 'color', 'gradient']),
        ...mapState(useDataflow, [
            'isAutoConnection',
            'servingList',
            'currentServing',
            'datasets',
            'groupOperators',
            'tasks',
            'execution',
            'pipelines',
            'operatorStyleDict'
        ]),
        flatFormatedOperators() {
            let operators = []
            for (let key in this.groupOperators) {
                operators.push(...this.groupOperators[key].items)
            }
            return operators
        },
        isTemplate() {
            if (!this.currentPipeline) return false
            let tags = this.currentPipeline.tags
            if (!Array.isArray(tags)) return false
            return tags.includes('template')
        },
        isAutoConnectionModel: {
            get() {
                return this.isAutoConnection
            },
            set(val) {
                this.switchAutoConnection(val)
            }
        },
        relatedTasks() {
            if (!this.currentPipeline) return []
            let tags = this.currentPipeline.tags
            if (!Array.isArray(tags)) return []
            if (tags.includes('template')) return []
            let result = []
            this.tasks.forEach((item) => {
                if (item.pipeline_id === this.currentPipeline.id) {
                    result.push(item)
                }
            })
            return result
        }
    },
    mounted() {
        this.setViewport()
        this.getServing()
        this.getPromptInfo()
        if (this.$route.query.task) this.openTaskHistory(this.$route.query.task)
        else if (this.$route.query.workflow) this.loadPlatformWorkflow()
        else if (this.$route.query.pipeline) this.loadLinkedPipeline(this.$route.query.pipeline)
        else this.restoreWorkspace()
        window.addEventListener('pagehide', this.persistWorkspace)
    },
    activated() { if (this.executionInfo.task_id) this.watchExecution(false) },
    deactivated() { this.persistWorkspace(); clearInterval(this.timer.exec) },
    beforeUnmount() {
        this.persistWorkspace()
        clearInterval(this.timer.exec); clearTimeout(this.uiSaveTimer)
        window.removeEventListener('pagehide', this.persistWorkspace)
    },
    methods: {
        scheduleWorkspaceSave() { if (this.workspaceRestoring || this.loadingPlatform || this.loadingLinkedPipeline) return; clearTimeout(this.uiSaveTimer); this.uiSaveTimer = setTimeout(() => this.persistWorkspace(), 600) },
        persistWorkspace() {
            if (this.workspaceRestoring || this.isMM || this.loadingPlatform || this.loadingLinkedPipeline) return
            const flow = useVueFlow(this.flowId)
            const nodes = flow.nodes.value.map(node => ({id:node.id,type:node.type,position:node.position,data:Object.fromEntries(Object.entries(node.data || {}).filter(([key]) => !['operatorLogs','operator_logs','loading','parameterLoading','parameterError','validationError'].includes(key)))}))
            return writeWorkspaceState('canvas', { nodes, edges:flow.edges.value.map(edge=>({id:edge.id,source:edge.source,target:edge.target,sourceHandle:edge.sourceHandle,targetHandle:edge.targetHandle,type:edge.type,data:edge.data})), sourceId:this.sourceDatabase?.id,
                pipeline:this.currentPipeline, taskId:this.executionInfo.task_id, viewport:flow.viewport.value, dirty:this.canvasDirty, route:this.$route.fullPath })
        },
        async restoreWorkspace() {
            const saved = readWorkspaceState('canvas')
            if (!saved?.nodes?.length && !saved?.taskId) { await this.$nextTick(); this.markCanvasSaved(); return }
            this.workspaceRestoring = true
            try {
                await Promise.all([this.getDatasets(), this.getOperators('zh')])
                if (saved.pipeline?.id) {
                    const response = await this.$api.pipelines.get_pipeline(saved.pipeline.id)
                    if (!response.success) throw new Error('保存的流程已不可用，请重新选择。')
                }
                this.currentPipeline = saved.pipeline || null
                this.sourceDatabase = this.datasets.find(dataset => dataset.id === saved.sourceId) || null
                const flow = useVueFlow(this.flowId)
                flow.$reset(); await this.$nextTick()
                flow.addNodes(saved.nodes.map(node => ({...node,data:{...node.data,flowId:this.flowId}})))
                flow.addEdges(saved.edges || [])
                if (saved.viewport) { flow.setViewport(saved.viewport); this.viewportRestored = true }
                await this.$nextTick()
                this.markCanvasSaved()
                if (saved.dirty) { this.canvasBaseline = 'recovered-draft'; this.canvasEdited = true; this.$barWarning('已恢复本机未保存的流程草稿。', {status:'correct'}) }
                if (saved.taskId) {
                    this.executionInfo.task_id = saved.taskId
                    this.lock.running = false
                    await this.refreshExecution()
                    if (!terminalStatuses.has(this.currentExecution.status)) this.watchExecution(false)
                }
            } catch (error) { this.$barWarning(error.message || '无法恢复本地流程，请重新选择。', {status:'warning'}) }
            finally { this.workspaceRestoring = false }
        },
        async addOperator(operator) {
            const nodeId = await this.$refs.canvas.addOperator(operator)
            await this.autoLayoutPipeline()
            this.$refs.canvas.inspectOperator(nodeId)
        },
        syncValidationErrors() {
            const ids = new Set(this.showPreflight ? this.preflightIssues.map(issue => issue.nodeId) : [])
            const flow = useVueFlow(this.flowId)
            for (const node of flow.nodes.value) if (!!node.data.validationError !== ids.has(node.id)) flow.updateNodeData(node.id, {validationError:ids.has(node.id)})
        },
        async inspectPreflight() {
            this.showPreflight = true
            if (this.preflightLoading) return
            this.preflightLoading = true
            const flow = useVueFlow(this.flowId), requests = new Map()
            try {
                await Promise.all(flow.nodes.value.filter(node => node.type === 'operator-node' && node.data.operatorParams).map(async node => {
                    const name = node.data.name
                    if (!requests.has(name)) requests.set(name,this.$api.operators.get_operator_detail_by_name(name))
                    const response = await requests.get(name)
                    if (response.code !== 200) return
                    const metadata = response.data?.parameter || {}
                    const current = flow.findNode(node.id)
                    if (!current || current.data.name !== name) return
                    const params = Object.fromEntries(['init','run'].map(kind=>[kind,(current.data.operatorParams[kind] || []).map(param=>({...param,required:(metadata[kind] || []).find(item=>item.name===param.name)?.required ?? param.required}))]))
                    flow.updateNodeData(node.id, {operatorParams:params})
                }))
            } catch (error) { this.$barWarning('部分参数定义暂时无法更新，运行时仍会再次校验。', {status:'warning'}) }
            finally { this.preflightLoading = false }
        },
        focusIssue(issue) {
            if (issue.kind === 'input') { this.openInputSettings(); return }
            if (!issue.nodeId) { if(issue.kind==='operator')this.show.operator = true; return }
            this.focusCanvasNode(issue.nodeId)
        },
        focusCanvasNode(id) {
            const flow = useVueFlow(this.flowId), node = flow.findNode(id)
            if (!node) return
            flow.setCenter(node.position.x + 130, node.position.y + 60, {zoom:Math.max(flow.viewport.value.zoom,0.85),duration:250})
            this.$refs.canvas?.inspectOperator(id)
        },
        async fitExecutionView() {
            await this.$nextTick()
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
            const flow=useVueFlow(this.flowId)
            if(flow.nodes.value.length)flow.fitView({padding:0.18,minZoom:0.15,maxZoom:1.1,duration:200})
        },
        focusExecutionStep(step) {
            const nodes = this.canvasNodes().filter(node => node.type === 'operator-node')
            const node = nodes.find(node => node.data.pipeline_idx === step.index + 1 && node.data.name === step.name)
            if (node) this.focusCanvasNode(node.id)
        },
        openExecutionResult() { this.historyTaskId = this.executionInfo.task_id; this.show.taskPanel = true },
        async refreshExecution() {
            const taskId = this.executionInfo.task_id
            if (!taskId) return
            try { await this.getExecution(taskId); if(taskId===this.executionInfo.task_id){this.pollError='';this.lock.running=terminalStatuses.has(this.execution.status)} }
            catch(error) { if(taskId===this.executionInfo.task_id)this.pollError='状态更新失败，将继续重试；当前显示上次状态。' }
        },
        async confirmCanvasChange(){if(!this.canvasDirty)return true;if(!await confirmDiscard(this))return false;this.canvasBaseline='';this.canvasEdited=false;return true},
        markCanvasEdited(){if(this.lock.loading && !this.loadingLinkedPipeline && !this.loadingPlatform)this.canvasEdited=true},
        markCanvasSaved(){this.canvasBaseline=this.canvasFingerprint;this.canvasEdited=false},
        async openTaskHistory(taskId) {
            this.historyTaskId = taskId
            try {
                const task = await this.platformRequest('get', `/tasks/execution/${encodeURIComponent(taskId)}/final-result`)
                if (this.$route.query.task !== taskId) return
                if (task.pipeline_id) await this.loadLinkedPipeline(task.pipeline_id)
                await this.handleWatchExecution({task_id:taskId})
                this.show.taskPanel = true
            } catch (e) { this.$barWarning(e.message, {status: 'error'}) }
        },
        async fitPlatformWhenReady() {
            if (this.workspaceRestoring || this.viewportRestored || (!this.currentPipeline && !this.isMM)) return
            const flow = useVueFlow(this.flowId)
            const count = this.isMM ? this.mmRecord?.config.steps.length : this.currentPipeline?.config?.operators.length
            const inputNodes = flow.findNode('db-node') ? 1 : 0
            if (flow.nodes.value.length !== count + inputNodes) return
            const key = this.$route.fullPath + flow.nodes.value.map(n => n.id).join(',')
            if (key === this.platformFitKey) return
            this.platformFitKey = key
            await this.$nextTick()
            flow.fitView({padding:0.22,duration:0})
            if(!this.canvasBaseline)this.markCanvasSaved()
        },
        async platformRequest(method, path, data) {
            const r = await http({method, url:'/api/v1'+path, data})
            if (!r.data.success) throw new Error(r.data.message || r.data.detail)
            return r.data.data
        },
        async loadPlatformWorkflow() {
            if (this.loadingPlatform) return
            this.canvasBaseline=''
            this.loadingPlatform = true
            this.platformFitKey = ''
            const targetRoute = this.$route.fullPath
            const workflow = this.$route.query.workflow
            const id = this.$route.query.config
            try {
                this.clearExecution()
                this.sourceDatabase = null
                if (workflow === 'text') {
                    await Promise.all([this.getDatasets(), this.getOperators('zh'), this.getPipelines()])
                    if (this.$route.fullPath !== targetRoute) return
                    const saved = this.pipelines.find(p => p.tags?.includes('platform-text'))
                    if (id || saved) await this.loadLinkedPipeline(id || saved.id)
                    else {
                        const t = await this.platformRequest('get', '/generation/template')
                        this.currentPipeline = {...t,id:null,name:'文本生成',tags:['platform-text']}
                        await this.recoverPipeline()
                    }
                } else if (workflow === 'multimodal') {
                    const records = await this.platformRequest('get', '/multimodal/configs')
                    const key = id || records[0]?.id
                    const record = await this.platformRequest('get', key ? '/multimodal/configs/'+key : '/multimodal/template')
                    if (this.$route.fullPath !== targetRoute) return
                    this.mmRecord = record
                    this.currentPipeline = {id:record.id,name:record.name,tags:['platform-mm']}
                    const flow = useVueFlow(this.flowId)
                    flow.$reset()
                    await this.$nextTick()
                    const graph = nativeMMGraph(record.config, this.flowId, this.operatorStyleDict)
                    flow.addNodes(graph.nodes)
                    flow.addEdges(graph.edges)
                }
                await this.$nextTick()
                await this.autoLayoutPipeline()
                this.markCanvasSaved()
            } catch (e) { this.$barWarning(e.message, {status:'error'}) }
            finally {
                this.loadingPlatform = false
                if (this.$route.path.replace(/\/$/, '') === '/m' && this.$route.query.workflow && this.$route.fullPath !== targetRoute) this.loadPlatformWorkflow()
            }
        },
        openInputSettings() {
            if (this.isMM) this.$router.push({path:'/m/multimodal',query:{config:this.mmRecord?.id}})
            else this.show.dataset = true
        },
        async saveMM() {
            try {
                const flow = useVueFlow(this.flowId)
                const expected = this.mmRecord.config.steps.map((s,i) => `${i ? 'mm-'+this.mmRecord.config.steps[i-1].id : 'db-node'}:mm-${s.id}`)
                if (flow.edges.value.length !== expected.length || !expected.every(key => flow.edges.value.some(e => `${e.source}:${e.target}` === key))) throw new Error('MM 模板执行顺序固定，请重新打开配置')
                const config = readNativeMM(this.mmRecord.config, flow.nodes.value)
                this.mmRecord = await this.platformRequest('post','/multimodal/configs',{
                    name:this.mmRecord.name,config,config_id:this.mmRecord.id || null
                })
                for (const s of this.mmRecord.config.steps) {
                    const node = flow.findNode('mm-'+s.id)
                    flow.updateNodeData(node.id, {...node.data,pipelineRole:`${node.data.status}：${Object.values(s.inputs).join(' + ')} → ${s.output}。`})
                }
                this.markCanvasSaved()
                this.$barWarning('MM 配置已保存；未做真实运行验证', {status:'correct'})
                return true
            } catch (e) { this.$barWarning(e.message, {status:'warning'}); return false }
        },

        async loadLinkedPipeline(id) {
            if (this.loadingLinkedPipeline) return
            this.loadingLinkedPipeline = true
            try {
                await Promise.all([this.getDatasets(), this.getOperators('zh'), this.getPipelines()])
                const response = await this.$api.pipelines.get_pipeline(id)
                if (!response.success) throw new Error(response.message)
                this.currentPipeline = response.data
                await this.recoverPipeline()
            } catch (error) { this.$barWarning(error.message, {status: 'error'}) } finally { this.loadingLinkedPipeline = false }
        },
        ...mapActions(useDataflow, [
            'switchAutoConnection',
            'getServingList',
            'getDataManagerList',
            'chooseServing',
            'getPipelines',
            'getPromptInfo',
            'getTasks',
            'getExecution',
            'clearExecution',
            'getDatasets',
            'getOperators'
        ]),
        setViewport() {
            const flow = useVueFlow(this.flowId)
            flow.setViewport({
                x: 0,
                y: 0,
                zoom: 1
            })
        },
        async autoLayoutPipeline() {
            const flow = useVueFlow(this.flowId)
            const { positions, hasCycle } = buildSnakeLayout(flow.nodes.value, flow.edges.value)
            if (hasCycle) {
                this.$barWarning(this.local('Pipeline is not a legal DAG'), {
                    status: 'warning'
                })
                return
            }
            if (!positions.size) return

            positions.forEach((position, nodeId) => {
                flow.updateNode(nodeId, { position })
            })
            await this.$nextTick()
            flow.fitView({ padding: 0.22, duration: 300 })
        },
        updateDatabaseNode() {
            if (!this.sourceDatabase) return
            const flow = useVueFlow(this.flowId)
            const existsNode = this.nodes.find((node) => node.type === 'database-node')
            if (existsNode) {
                flow.updateNodeData(existsNode.id, {
                    ...existsNode.data,
                    label: this.sourceDatabase.name,
                    ...this.sourceDatabase
                })
            } else {
                let position = { x: 50, y: 160 }
                // location 可能缺失、或 agent config 里是占位的 [0,0]；这两种
                // 情况都用可见的默认位（算子节点在 x:350，dataset 放其左侧），
                // 避免 db-node 落在 (0,0) 与视口/算子重叠而"看不见"。
                const loc = this.sourceDatabase.location
                if (Array.isArray(loc) && (loc[0] || loc[1])) {
                    position.x = loc[0]
                    position.y = loc[1]
                }
                flow.addNodes({
                    id: 'db-node',
                    type: 'database-node',
                    position,
                    data: {
                        flowId: this.flowId,
                        label: this.sourceDatabase.name,
                        ...this.sourceDatabase
                    }
                })
            }
        },
        confirmDataset(dataset, refresh = false) {
            if(!refresh)this.markCanvasEdited()
            this.sourceDatabase = dataset
            this.show.dataset = false
            if (refresh) this.updateDatabaseNode()
        },
        async getServing() {
            if (!this.lock.serving) return
            this.lock.serving = false
            await this.getServingList()
            await this.getDataManagerList()
            this.lock.serving = true
        },
        showServing($event) {
            $event.preventDefault()
            $event.stopPropagation()
            this.$refs.servingMenu.rightClick($event, document.body)
        },
        syncRunValue(item) {
            const flow = useVueFlow(this.flowId)
            let edges = flow.edges.value.filter((edge) => edge.source === item.nodeId)
            for (let edge of edges) {
                let sourceKeyName = edge.sourceHandle ? edge.sourceHandle.split('::')[0] : null
                if (sourceKeyName !== item.name) continue
                let targetNode = flow.findNode(edge.target)
                let targetKeyName = edge.targetHandle ? edge.targetHandle.split('::')[0] : null
                if (targetNode) {
                    let targetIndex = targetNode.data.operatorParams.run.findIndex(
                        (item) => item.name === targetKeyName
                    )
                    if (targetIndex !== -1) {
                        targetNode.data.operatorParams.run[targetIndex].value = item.value
                    }
                }
            }
        },
        sortPipeline() {
            let flow = useVueFlow(this.flowId)
            let nodeMap = {}
            flow.nodes.value.forEach((node) => {
                nodeMap[node.id] = {
                    id: node.id,
                    target: [],
                    source: []
                }
            })
            let N_nodes = flow.nodes.value.length
            let edges = flow.edges.value
            edges.forEach((edge) => {
                const { source, target } = edge
                nodeMap[source].target.push(target)
                nodeMap[target].source.push(source)
            })
            let results = []
            let outNodes = Object.values(nodeMap).filter((node) => node.source.length === 0)
            while (outNodes.length > 0) {
                let allTargetNodes = []
                let exists = {}
                for (let node of outNodes) {
                    results.push(node)
                    let targetIds = node.target
                    for (let targetId of targetIds) {
                        let targetNode = nodeMap[targetId]
                        targetNode.source = targetNode.source.filter((item) => item !== node.id)
                        if (!exists[targetNode.id]) {
                            allTargetNodes.push(targetNode)
                            exists[targetNode.id] = 1
                        }
                    }
                }
                outNodes = allTargetNodes.filter((node) => node.source.length === 0)
            }
            console.log(results, N_nodes)
            if (results.length !== N_nodes) {
                this.$barWarning(this.local('Pipeline is not a legal DAG'), {
                    status: 'warning'
                })
                return
            }
            let nodeOperators = []
            results.forEach((node) => {
                if (node.id === 'db-node') return
                let oriNode = flow.findNode(node.id)
                flow.updateNodeData(oriNode.id, { pipeline_idx: nodeOperators.length + 1 })
                nodeOperators.push({
                    name: oriNode.data.name,
                    params: oriNode.data.operatorParams,
                    location: [oriNode.position.x, oriNode.position.y],
                    pipeline_role: oriNode.data.pipelineRole || null
                })
            })
            return nodeOperators
        },
        async handleSaveClick() {
            if (this.isMM) return await this.saveMM()
            if (!this.currentPipeline || !this.currentPipeline.id) {
                this.show.pipelinePanel = true
                return false
            }
            let tags = this.currentPipeline.tags
            if (!Array.isArray(tags)) tags = []
            if (tags.includes('template')) {
                this.show.pipelinePanel = true
                return false
            }
            return await this.savePipeline()
        },
        async savePipeline() {
            if (this.nodes.some(n => n.data?.externalTemplate)) { this.$barWarning('外部 MM 配置不能写入核心 Pipeline', {status:'warning'}); return false }
            if (!this.sourceDatabase) {
                this.$barWarning(this.local('Please select a dataset'), {
                    status: 'warning'
                })
                return false
            }
            let cancel = false
            if (this.executionInfo.task_id) {
                await new Promise((resolve) => {
                    this.$infoBox(
                        this.local(
                            'Are you sure to override the pipeline with the execution task?'
                        ),
                        {
                            status: 'warning',
                            confirm: () => {
                                cancel = false
                                resolve()
                            },
                            cancel: () => {
                                cancel = true
                                resolve()
                            }
                        }
                    )
                })
            }
            if (cancel) return false
            let nodeOperators = this.sortPipeline()
            const flow = useVueFlow(this.flowId)
            let dbNode = flow.findNode('db-node')
            return await this.$api.pipelines
                .update_pipeline(this.currentPipeline.id, {
                    name: this.currentPipeline.name,
                    config: {
                        file_path: this.currentPipeline.config.file_path,
                        execution_options: this.currentPipeline.config.execution_options || {},
                        input_dataset: {
                            id: this.sourceDatabase.id,
                            location: [dbNode.position.x, dbNode.position.y],
                            pipeline_role: dbNode.data.pipelineRole || null
                        },
                        operators: nodeOperators
                    }
                })
                .then((res) => {
                    if (res.code === 200) {
                        this.getPipelines()
                        this.markCanvasSaved()
                        this.$barWarning(this.local('Pipeline has been updated'), {
                            status: 'correct'
                        })
                        return true
                    }
                    this.$barWarning(res.message || this.local('Pipeline update failed'), {status:'error'})
                    return false
                })
                .catch((err) => {
                    this.$barWarning(this.local('Pipeline update failed'), {
                        status: 'error'
                    })
                    return false
                })
        },
        async addPipeline(name) {
            if (!this.sourceDatabase) {
                this.$barWarning(this.local('Please select a dataset'), {
                    status: 'warning'
                })
                return
            }
            let nodeOperators = this.sortPipeline()
            const flow = useVueFlow(this.flowId)
            let dbNode = flow.findNode('db-node')
            if (!dbNode) {
                this.$barWarning(this.local('Please select a dataset'), {
                    status: 'warning'
                })
                return
            }
            if (this.currentPipeline?.tags?.includes('platform-text')) {
                try {
                    this.currentPipeline = await this.platformRequest('post','/generation/configs', {
                        name, config:{...this.currentPipeline.config,
                            input_dataset:{id:this.sourceDatabase.id,location:[dbNode.position.x,dbNode.position.y]},
                            operators:nodeOperators}
                    })
                    this.resumeRunAfterSave()
                    this.show.pipelinePanel = false
                    await this.getPipelines()
                    this.markCanvasSaved()
                    this.$barWarning(this.local('Pipeline has been created'), {status:'correct'})
                } catch (e) { this.$barWarning(e.message, {status:'warning'}) }
                return
            }
            return await this.$api.pipelines
                .create_pipeline({
                    name: name,
                    tags: this.currentPipeline?.tags?.includes('platform-text') ? ['platform-text','sft'] : [],
                    config: {
                        file_path: '',
                        execution_options: this.currentPipeline?.config?.execution_options || {},
                        input_dataset: {
                            id: this.sourceDatabase.id,
                            location: [dbNode.position.x, dbNode.position.y],
                            pipeline_role: dbNode.data.pipelineRole || null
                        },
                        operators: nodeOperators
                    }
                })
                .then((res) => {
                    if (res.code === 200) {
                        this.getPipelines()
                        if (!this.currentPipeline || !this.currentPipeline.id || this.isTemplate) {
                            this.currentPipeline = res.data
                        }
                        this.markCanvasSaved()
                    this.$barWarning(this.local('Pipeline has been created'), {
                            status: 'correct'
                        })
                        this.resumeRunAfterSave()
                        this.show.pipelinePanel = false
                    } else {
                        this.$barWarning(res.message || this.local('Pipeline update failed'), {status: 'error'})
                    }
                })
                .catch((err) => {
                    this.$barWarning(err?.message || this.local('Pipeline update failed'), {status: 'error'})
                })
        },
        async executePipeline(runOptions) {
            if (this.isMM) {
                try { await this.platformRequest('post', `/multimodal/configs/${this.mmRecord.id}/submit`) }
                catch (e) { this.$barWarning(e.message, {status:'warning'}); this.lock.running = true }
                return
            }
            if (this.nodes.some(n => n.data?.externalTemplate)) { this.$barWarning('外部 MM 步骤不能提交到核心执行器', {status:'warning'}); this.lock.running = true; return }
            if (!this.currentPipeline || !this.currentPipeline.id) {
                this.$barWarning(this.local('Please select a pipeline'), {
                    status: 'warning'
                })
                return
            }
            await this.platformRequest('post', `/tasks/execute-async?pipeline_id=${encodeURIComponent(this.currentPipeline.id)}`, runOptions)
                .then((data) => ({code: 200, data}))
                .then((res) => {
                    if (res.code === 200) {
                        this.clearExecution()
                        this.executionInfo.task_id = res.data.task_id
                        this.refreshExecution()
                        this.watchExecution()
                        this.$barWarning(this.local('Pipeline has been executed'), {
                            status: 'correct'
                        })
                    }
                    else {
                        this.$barWarning(this.local('Pipeline execution failed') + res.message, {
                            status: 'warning'
                        })
                        this.lock.running = true
                    }
                })
                .catch((err) => {
                    this.$barWarning(err?.response?.data?.message || err?.message || this.local('Pipeline execution failed'), {
                        status: 'error'
                    })
                    this.lock.running = true
                })
        },
        async openRunConfirm() {
            if (this.runPreparing || this.show.runConfirm || this.pendingRun) return
            if (!this.lock.running) { this.$barWarning(this.local('Please wait for the previous pipeline to finish'), {status:'warning'}); return }
            if (this.isMM) { this.$barWarning('图片流程当前未启用运行', {status:'warning'}); return }
            this.runPreparing = true
            try {
                await this.inspectPreflight()
                if (this.preflightIssues.length) { this.focusIssue(this.preflightIssues[0]); return }
                const saved = await this.handleSaveClick()
                if (saved) this.show.runConfirm = true
                else if (this.show.pipelinePanel) this.pendingRun = true
            } catch(e) { this.$barWarning(e.message, {status:'error'}) }
            finally { this.runPreparing = false }
        },
        resumeRunAfterSave() {
            if (!this.pendingRun) return
            this.pendingRun = false
            this.show.runConfirm = true
        },
        async handleRunClick(runOptions) {
            if (!this.lock.running) return
            this.lock.running = false
            // Pipeline was saved before opening the single run-settings dialog.
            try { await this.executePipeline(runOptions) }
            catch(e) { this.lock.running = true; this.$barWarning(e.message, {status:'error'}) }
        },
        showExecDetails(pipeline_idx) {
            if (!this.executionInfo.task_id) return
            this.executionInfo.currentStep = pipeline_idx - 1
            this.$api.tasks
                .get_task_result(this.executionInfo.task_id, this.executionInfo.currentStep, 15)
                .then((res) => {
                    if (res.code === 200) {
                        this.executionInfo.runningResult = res.data
                        this.show.execResult = true
                    }
                })
        },
        pathJoin(...parts) {
            return parts
                .map((part, index) => {
                    if (index === 0) {
                        return part.replace(/\/+$/, '')   // 去掉结尾 /
                    }
                    return part.replace(/^\/+|\/+$/g, '') // 去掉两边 /
                })
                .join('/')
        },
        downloadData(pipeline_idx) {
            if (!this.executionInfo.task_id) return
            let baseURL = axios.defaults.baseURL
            let url =
                this.pathJoin(baseURL,
                    `/api/v1/tasks/execution/${this.executionInfo.task_id}/download?step=${pipeline_idx - 1}`)
            window.open(url, '_blank')
        },
        async selectPipelineCallback(pipeline) {
            if (pipeline?.id) this.currentPipeline = pipeline
            this.clearExecution()
            this.executionInfo.task_id = null
            this.show.pipeline = false
            this.viewportRestored = false
            await this.$nextTick()
            await this.autoLayoutPipeline()
            this.markCanvasSaved()
        },
        async selectExecutionPipeline(config) {
            console.log(config)
            if (!this.lock.loading) return
            this.lock.loading = false
            try {
                const confirmDatasetCall = (_, dataset) => {
                    this.confirmDataset(dataset, true)
                }
                await usePipelineOperation().renderPipeline(
                    config,
                    this.flowId,
                    this.datasets,
                    this.flatFormatedOperators,
                    this,
                    this.$nextTick,
                    confirmDatasetCall,
                    this.$Guid
                )
            } finally {
                this.lock.loading = true
            }
        },
        async recoverPipeline() {
            if(!await this.confirmCanvasChange())return
            if (!this.currentPipeline || !this.currentPipeline.config) {
                return
            }
            this.lock.loading = false
            try {
                const confirmDatasetCall = (_, dataset) => {
                    this.confirmDataset(dataset, true)
                }
                await usePipelineOperation().renderPipeline(
                    this.currentPipeline.config,
                    this.flowId,
                    this.datasets,
                    this.flatFormatedOperators,
                    this,
                    this.$nextTick,
                    confirmDatasetCall,
                    this.$Guid
                )
                await this.selectPipelineCallback()
            } finally {
                this.lock.loading = true
            }
        },
        async handleWatchExecution({ task_id }) {
            if (!await this.confirmCanvasChange()) return
            this.executionInfo.task_id = task_id
            this.lock.running = false
            try {
                await this.getExecution(task_id)
                if(this.executionInfo.task_id !== task_id)return
                await this.selectExecutionPipeline(this.execution.pipeline_config)
                await this.autoLayoutPipeline()
                this.markCanvasSaved()
                this.lock.running = terminalStatuses.has(this.execution.status)
            } catch(error) { this.pollError = '暂时无法加载任务详情，将继续重试。' }
            finally { if(this.executionInfo.task_id === task_id)this.watchExecution(false) }
        },
        watchExecution(revealResult = true) {
            if (!this.executionInfo.task_id) return
            const taskId = this.executionInfo.task_id
            clearInterval(this.timer.exec)
            let fetching = false
            this.timer.exec = setInterval(async () => {
                if(fetching)return
                fetching = true
                try { await this.getExecution(taskId); this.pollError = '' } catch(error) { this.pollError = '状态更新失败，将继续重试；当前显示上次状态。'; return } finally { fetching = false }
                if (this.executionInfo.task_id !== taskId) return
                this.lock.running = false
                if (this.execution.status === 'completed') {
                    clearInterval(this.timer.exec)
                    this.lock.running = true
                    if (revealResult) {
                        this.historyTaskId = taskId
                        const collection = this.execution.auto_collection
                        this.$barWarning(collection?.status === 'collected' ? '运行完成，已自动收录到生成数据集。' : '运行完成，可在底部查看结果、收录或下载。', {status: collection?.status === 'failed' ? 'warning' : 'correct'})
                    }
                } else if (this.execution.status === "cancelled") {
                    clearInterval(this.timer.exec)
                    this.lock.running = true
                } else if (this.execution.status === 'failed') {
                    clearInterval(this.timer.exec)
                    this.lock.running = true
                    this.$barWarning(
                        this.local(
                            'Pipeline execution failed:' + (Object.values(this.execution.operators_detail || {}).find(step=>step.error)?.error || '请在底部运行面板查看失败步骤与日志。')
                        ),
                        {
                            status: 'error',
                            autoClose: -1
                        }
                    )
                }
            }, 3000)
        },
        stopExecution() {
            if (!this.currentPipeline || !this.currentPipeline.config) return
            if (!this.executionInfo.task_id) return
            if (!['running','pending','queued','initializing'].includes(this.execution.status)) {
                this.$barWarning(this.local('Pipeline execution not running'), {
                    status: 'warning'
                })
                return
            }
            this.stopping = true
            this.$api.tasks.kill_execution(this.executionInfo.task_id).then((res) => {
                if (res.code === 200) {
                    this.refreshExecution()
                    this.$barWarning(this.local('Pipeline execution stopped'), {
                        status: 'correct'
                    })
                }
            }).catch(error=>this.$barWarning(error.message || '停止失败，请重试', {status:'error'})).finally(()=>{this.stopping=false})
        },
        onConnect(connection) {
            if (this.isMM) { this.$barWarning('MM 模板步骤顺序固定，请在参数面板修改字段绑定', {status:'warning'}); return }
            const { source, sourceHandle, target, targetHandle } = connection
            let sourceHandleObj = this.useEdgeSync.decHandle(sourceHandle)
            let targetHandleObj = this.useEdgeSync.decHandle(targetHandle)
            let sourceType = sourceHandleObj.direction
            let targetType = targetHandleObj.direction
            let sourceKeyName = sourceHandleObj.name
            let targetKeyName = targetHandleObj.name
            let sourceKeyType = sourceHandleObj.edgeType
            let targetKeyType = targetHandleObj.edgeType
            if (sourceType === targetType) return
            if (sourceKeyType !== targetKeyType) {
                this.$barWarning(this.local('Illegal connection'), {
                    status: 'warning'
                })
                return
            }
            const flow = useVueFlow(this.flowId)
            let existsEdge = this.edges.find(
                (edge) =>
                    edge.source === source &&
                    edge.target === target &&
                    edge.sourceHandle === sourceHandle &&
                    edge.targetHandle === targetHandle
            )
            if (existsEdge) {
                if (existsEdge.data.edgeType === 'node' && this.isAutoConnection) {
                    this.useEdgeSync.removeRunEdges(source, target, this.flowId)
                }
                flow.removeEdges(existsEdge.id)
            } else {
                flow.addEdges({
                    id: this.$Guid(),
                    type: 'base-edge',
                    source: source,
                    target: target,
                    sourceHandle: sourceHandle,
                    targetHandle: targetHandle,
                    animated: sourceKeyType !== 'node',
                    data: {
                        label: sourceKeyType === 'node' ? 'Node' : 'Key',
                        edgeType: sourceKeyType
                    }
                })
                if (sourceKeyType === 'run_key') {
                    let sourceNode = flow.findNode(source)
                    let targetNode = flow.findNode(target)
                    if (sourceNode && targetNode) {
                        let targetIndex = targetNode.data.operatorParams.run.findIndex(
                            (item) => item.name === targetKeyName
                        )
                        let sourceIndex = sourceNode.data.operatorParams.run.findIndex(
                            (item) => item.name === sourceKeyName
                        )
                        if (targetIndex !== -1 && sourceIndex !== -1) {
                            targetNode.data.operatorParams.run[targetIndex].value =
                                sourceNode.data.operatorParams.run[sourceIndex].value
                        }
                    }
                } else {
                    if (this.isAutoConnection)
                        this.useEdgeSync.autoConnectRunEdges(
                            source,
                            target,
                            this.flowId,
                            this.$Guid
                        )
                }
            }
        },
        onConnectStart(params) { },
        onConnectEnd(event) {
            console.log(event)
        },
        resetFlow() {
            this.$infoBox(this.local('Are you sure to reset the flow?'), {
                status: 'error',
                theme: this.theme,
                confirm: () => {
                    const flow = useVueFlow(this.flowId)
                    flow.$reset()
                }
            })
        },

    }
}
</script>

<style lang="scss">
.df-default-container {
    position: relative;
    width: 100%;
    height: 100%;
    padding: 15px;
    background-color: rgba(241, 241, 241, 1);
    display: flex;

    &.dark {
        background: rgba(36, 36, 36, 1);

        .df-flow-container {
            background: rgba(30, 30, 30, 1);
            border: rgba(90, 90, 90, 0.1) solid thin;
        }

        .control-menu-block {
            .command-bar {
                .option-name {
                    color: whitesmoke;
                }
            }
        }
    }

    .df-pipeline-container {
        position: absolute;
        left: 0px;
        top: 15px;
        width: 300px;
        height: calc(100% - 30px);
        border-top-left-radius: 15px;
        border-bottom-left-radius: 15px;
        box-shadow: 1px 0px 2px rgba(120, 120, 120, 0.1);
        z-index: 2;
    }

    .df-flow-container {
        position: relative;
        width: 100%;
        height: 100%;
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        background: rgba(250, 250, 250, 1);
        border: rgba(120, 120, 120, 0.1) solid thin;
        border-radius: 15px;
        overflow: hidden;
        container-type: inline-size;

        > .df-main-flow-container {
            order: 2;
            flex: 1;
            min-height: 0;
            height: 0;
        }
    }

    .control-menu-block {
        position: relative;
        width: 100%;
        padding: 10px 12px;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
        border-bottom: 1px solid rgba(120, 120, 120, 0.14);
        background: rgba(250, 250, 250, 0.96);
        z-index: 1;

        > .command-bar-right-space {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 6px;
            min-width: 0;
        }

        .command-bar {
            min-width: 240px;
            flex: 1;
            width: auto;
            border: 0;
            border-radius: 6px;
            box-shadow: none;

            .command-bar-item {
                &:hover {
                    .option-img {
                        filter: grayscale(0);
                    }
                }
            }

            .command-bar-item-wrapper {
                position: relative;
                width: 100%;
                height: 100%;
                display: flex;
                align-items: center;

                &:hover {
                    .option-img {
                        filter: grayscale(0);
                    }
                }
            }

            .option-img {
                width: auto;
                height: 15px;
                filter: grayscale(100%);
                transition: filter 0.2s;
            }

            .option-name {
                margin-left: 8px;
                font-size: 12px;
                color: rgba(45, 48, 56, 1);
            }
        }
    }
}

.df-default-container.dark .control-menu-block {
    background: rgba(30, 30, 30, 0.98);
    border-bottom-color: rgba(255, 255, 255, 0.12);
}

@container (max-width: 880px) {
    .control-menu-block > .command-bar,
    .control-menu-block > .command-bar-right-space {
        flex: 1 1 100%;
    }
}


.canvas-empty-state {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 24px;
    color: #737780;
    text-align: center;
    pointer-events: none;

    > i { font-size: 36px; color: rgba(69, 98, 213, 0.65); }
    h2 { font-size: 17px; font-weight: 600; color: #454b58; }
    p { font-size: 13px; line-height: 1.7; }
    .canvas-start-button { pointer-events: auto; margin-top: 4px; }
}
.df-default-container.dark .canvas-empty-state h2 { color: #e5e7eb; }

@media (max-width: 1024px) {
    .control-menu-block > .df-current-pipeline-container {
        padding-left: 26px;
    }
}

.serving-menu {
    .serving-item {
        position: relative;
        flex-direction: column;
        line-height: 1.5;

        &.choosen {
            &::before {
                content: '';
                position: absolute;
                left: 0px;
                top: 10px;
                width: 3px;
                height: calc(100% - 20px);
                background: linear-gradient(135deg, rgba(69, 98, 213, 1), #ff0080);
                border-radius: 8px;
            }

            .main-title {
                @include color-rainbow;

                color: rgba(69, 98, 213, 1);
            }
        }

        .main-title {
            font-size: 16px;
        }

        .sec-title {
            font-size: 10px;
            color: rgba(120, 120, 120, 1);
        }
    }
}

.df-scale-up-to-up-enter-active {
    animation: scaleUp 0.7s ease both;
    animation-delay: 0.3s;
}

.df-scale-up-to-up-leave-active {
    position: absolute;
    width: 100%;
    height: 100%;
    display: flex;
    justify-content: center;
    align-items: center;
    animation: scaleDownUp 0.7s ease both;
    z-index: 8;
}

@keyframes scaleUp {
    from {
        opacity: 0;
        transform: scale(0.3);
    }
}

@keyframes scaleDownUp {
    to {
        opacity: 0;
        transform: scale(1.2);
    }
}
</style>

<style scoped>.wizard-return{position:absolute;top:12px;right:24px;z-index:20;background:white;padding:8px 16px;border-radius:8px;color:#4e5bd5}</style>

<style scoped>
.canvas-preflight{position:absolute;top:108px;left:16px;z-index:4;width:min(420px,calc(100% - 32px));max-height:45%;overflow:auto;padding:14px;background:#fafafa;border:1px solid #e0e4ed;border-radius:8px;box-shadow:0 4px 18px #26304714;color:#39465d;font-size:12px}.canvas-preflight.dark{background:#242424;color:#dce1ed;border-color:#3d414b}.canvas-preflight header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}.canvas-preflight header button{background:transparent;border:0;color:inherit;font-size:20px;cursor:pointer}.canvas-preflight p{line-height:1.7;color:#78849a}.preflight-issue{display:block;width:100%;padding:9px 0;text-align:left;border:0;border-top:1px solid #80808022;background:transparent;color:inherit;cursor:pointer;line-height:1.6;font:inherit}.preflight-issue span{display:block;font-weight:600;color:#b36c36}
</style>
