import { team } from '@/components/manage/team/client'
import { ref, computed, onScopeDispose } from 'vue'
import { defineStore } from 'pinia'
import { getCurrentInstance } from 'vue'
import axios from 'axios'
import {subscribeChanges} from '@/components/manage/forms/changes'

export const useDataflow = defineStore('useDataflow', () => {
    const instance = getCurrentInstance()
    const proxy = instance.proxy

    const getKeyText = (text) => {
        let splitText = text.split('_')
        return splitText.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
    }

    const operatorStyleDict = ref({
        default: {
            icon: 'Flag',
            statusColor: 'rgba(0, 153, 204, 1)',
            iconColor: 'rgba(255, 255, 255, 1)',
            iconBackground:
                'linear-gradient(90deg, rgba(73, 131, 251, 1) 0%, rgba(100, 161, 252, 1) 100%)',
            borderColor: 'rgba(73, 131, 251, 0.6)',
            shadowColor: 'rgba(73, 131, 251, 0.1)'
        },
        parser: {
            icon: 'Document',
            statusColor: 'rgba(255, 153, 0, 1)',
            iconColor: 'rgba(255, 255, 255, 1)',
            iconBackground:
                'linear-gradient(90deg, rgba(255, 153, 0, 1) 0%, rgba(255, 204, 0, 1) 100%)',
            borderColor: 'rgba(255, 153, 0, 0.6)',
            shadowColor: 'rgba(255, 153, 0, 0.1)'
        },
        filter: {
            icon: 'PostUpdate',
            statusColor: 'rgba(255, 102, 0, 1)',
            iconColor: 'rgba(255, 255, 255, 1)',
            iconBackground:
                'linear-gradient(90deg, rgba(255, 102, 0, 1) 0%, rgba(255, 153, 0, 1) 100%)',
            borderColor: 'rgba(255, 102, 0, 0.6)',
            shadowColor: 'rgba(255, 102, 0, 0.1)'
        },
        generate: {
            icon: 'Library',
            statusColor: 'rgba(255, 51, 0, 1)',
            iconColor: 'rgba(255, 255, 255, 1)',
            iconBackground:
                'linear-gradient(90deg, rgba(255, 51, 0, 1) 0%, rgba(255, 102, 0, 1) 100%)',
            borderColor: 'rgba(255, 51, 0, 0.6)',
            shadowColor: 'rgba(255, 51, 0, 0.1)'
        },
        eval: {
            icon: 'Bullseye',
            statusColor: 'rgba(255, 0, 0, 1)',
            iconColor: 'rgba(255, 255, 255, 1)',
            iconBackground:
                'linear-gradient(90deg, rgba(255, 0, 0, 1) 0%, rgba(255, 51, 0, 1) 100%)',
            borderColor: 'rgba(255, 0, 0, 0.6)',
            shadowColor: 'rgba(255, 0, 0, 0.1)'
        },
        refine: {
            icon: 'Market',
            statusColor: 'rgba(0, 153, 0, 1)',
            iconColor: 'rgba(255, 255, 255, 1)',
            iconBackground:
                'linear-gradient(90deg, rgba(0, 153, 0, 1) 0%, rgba(0, 204, 0, 1) 100%)',
            borderColor: 'rgba(0, 153, 0, 0.6)',
            shadowColor: 'rgba(0, 153, 0, 0.1)'
        }
    })
    const operators = ref([])
    const groupOperators = ref({})
    const getOperators = async (lang = 'zh') => {
        await proxy.$api.operators.list_operators(lang).then((res) => {
            if (res.code === 200) {
                operators.value = res.data
                groupOperators.value = {}
                for (let operator of operators.value) {
                    let styleKey = operator.type.level_2
                    if (!operatorStyleDict.value[styleKey]) {
                        styleKey = 'default'
                    }
                    operator = {
                        status: getKeyText(operator.type.level_2),
                        statusColor: operatorStyleDict.value[styleKey].statusColor,
                        label: operator.name,
                        icon: operatorStyleDict.value[styleKey].icon,
                        iconColor: operatorStyleDict.value[styleKey].iconColor,
                        iconBackground: operatorStyleDict.value[styleKey].iconBackground,
                        borderColor: operatorStyleDict.value[styleKey].borderColor,
                        shadowColor: 'rgba(0, 0, 0, 0.05)',
                        nodeShadowColor: operatorStyleDict.value[styleKey].shadowColor,
                        enableDelete: false,
                        show: true,
                        ...operator
                    }

                    if (groupOperators.value[operator.type.level_1]) {
                        groupOperators.value[operator.type.level_1].items.push(operator)
                    } else {
                        groupOperators.value[operator.type.level_1] = {
                            key: operator.type.level_1,
                            name: getKeyText(operator.type.level_1),
                            items: [operator],
                            expand: true
                        }
                    }
                }
            } else {
                proxy.$barWarning(res.message, {
                    status: 'warning'
                })
            }
        })
    }

    const promptInfo = ref({})
    const getPromptInfo = async () => {
        await proxy.$api.prompts.get_prompt_info_api_v1_prompts_prompt_info_get().then((res) => {
            if (res.code === 200) {
                promptInfo.value = res.data.prompts
            } else {
                proxy.$barWarning(res.message, {
                    status: 'warning'
                })
            }
        })
    }

    const datasets = ref([])
    const visibleDatasets = computed(() => datasets.value.filter(item => item.is_visible !== false))
    let datasetVersion=0
    const getDatasets = async () => {
        const version=++datasetVersion
        let res = await proxy.$api.datasets.list_datasets().catch((err) => {
            proxy.$barWarning(err, {
                status: 'error'
            })
        })
        if(version!==datasetVersion || !res)return
        if (res.success) {
            let _datasets = res.data
            _datasets.forEach((item) => {
                item.showPreview = false
                item.expanded = false
            })
            datasets.value = _datasets
        } else {
            proxy.$barWarning(res.message, {
                status: 'warning'
            })
        }
    }

    const text2sqlDatasets = ref([])
    const getText2SqlDatasets = async () => {
        if(team.enabled){text2sqlDatasets.value=[];return}
        await proxy.$api.text2sql_database.list_databases().then((res) => {
            if (res.code === 200) {
                text2sqlDatasets.value = res.data
            } else {
                proxy.$barWarning(res.message, {
                    status: 'warning'
                })
            }
        })
    }

    const servingList = ref([])
    const currentServing = ref(null)
    const getServingList = async () => {
        return await proxy.$api.serving.list_serving_instances_api_v1_serving__get().then((res) => {
            if (res.code === 200) {
                res.data.forEach((item) => {
                    item.key = item.id
                    item.text = item.name
                })
                servingList.value = res.data
            } else {
                proxy.$barWarning(res.message, {
                    status: 'warning'
                })
            }
            return res
        })
    }
    const chooseServing = (item) => {
        currentServing.value = item
    }

    const dataManagerList = ref([])
    const getDataManagerList = async () => {
        if(team.enabled){dataManagerList.value=[];return}
        await proxy.$api.text2sql_database_manager.list_text2sql_database_managers().then((res) => {
            if (res.code === 200) {
                res.data.forEach((item) => {
                    item.key = item.id
                    item.text = item.name
                })
                dataManagerList.value = res.data
            } else {
                proxy.$barWarning(res.message, {
                    status: 'warning'
                })
            }
        })
    }

    const pipelines = ref([])
    const getPipelines = async () => {
        await proxy.$api.pipelines.list_pipelines().then((res) => {
            if (res.code === 200) {
                let _pipelines = res.data
                _pipelines.forEach((item) => {
                    item.show = true
                })
                _pipelines.sort((a, b) => {
                    return new Date(b.updated_at) - new Date(a.updated_at)
                })
                pipelines.value = _pipelines
            }
        })
    }

    const tasks = ref([])
    const getTasks = async () => {
        await proxy.$api.tasks.list_executions().then((res) => {
            if (res.code === 200) {
                let _tasks = res.data
                tasks.value = _tasks
            }
        })
    }

    const execution = ref({})
    const executionStep = ref(null)
    let executionRequest = 0
    const getExecution = async (task_id) => {
        const version = ++executionRequest
        const res = await proxy.$api.tasks.get_execution_status(task_id)
        if (version !== executionRequest) return
        if (res.code !== 200 || !res.data) throw new Error(res.message || '无法获取任务状态')
        execution.value = res.data
        const steps = Object.values(res.data.operators_detail || {})
        executionStep.value = steps.find(step => step.status === 'running')?.index ??
            steps.filter(step => step.status === 'completed').reduce((last, step) => Math.max(last ?? -1, step.index), null)
    }
    const clearExecution = () => {
        executionRequest++
        execution.value = {}
        executionStep.value = null
    }

    const isAutoConnection = ref(false)

    const switchAutoConnection = (val) => {
        isAutoConnection.value = val
    }

    // JSON Schemas — available schemas users saved on the "schemas" page.
    // These power the json_schema value-input on operator params.
    const jsonSchemaList = ref([])
    let schemaVersion=0
    const getJsonSchemaList = async () => {
        const version=++schemaVersion
        try {
            const res = await axios.get('/api/v1/json_schemas?include_builtin=true')
            const payload = res.data && res.data.data ? res.data.data : res.data
            const list = Array.isArray(payload) ? payload : []
            // normalise for fv-combobox consumption
            list.forEach((item) => {
                item.key = item.id
                item.text = item.name
            })
            if(version===schemaVersion)jsonSchemaList.value = list
        } catch (e) {
            // silent — schemas page is optional
        }
    }

    const stopChanges=subscribeChanges(change=>{if(change.topic==='resources')getJsonSchemaList();if(change.topic==='datasets')getDatasets()})
    onScopeDispose(stopChanges)

    return {
        operatorStyleDict,
        operators,
        groupOperators,
        getOperators,
        promptInfo,
        getPromptInfo,
        datasets,
        visibleDatasets,
        getDatasets,
        text2sqlDatasets,
        getText2SqlDatasets,
        servingList,
        currentServing,
        getServingList,
        chooseServing,
        dataManagerList,
        getDataManagerList,
        pipelines,
        getPipelines,
        tasks,
        getTasks,
        execution,
        executionStep,
        getExecution,
        clearExecution,
        isAutoConnection,
        switchAutoConnection,
        jsonSchemaList,
        getJsonSchemaList
    }
})
