<template>
    <main class="resources" :class="{ dark: theme === 'dark' }">
        <header>
            <div>
                <h1>{{ isPrompt ? 'Prompt Manager' : 'JSON Schema Manager' }}</h1>
                <p>
                    {{
                        isPrompt
                            ? '管理提示词，查看用途、变量与流程引用。'
                            : '管理结构规则，预览示例与校验结果。'
                    }}
                </p>
            </div>
            <div class="actions">
                <button :disabled="busy" @click="load">刷新</button
                ><button class="primary" @click="create">
                    {{ isPrompt ? '＋ 新建模板' : '＋ 新建 Schema' }}
                </button>
            </div>
        </header>
        <p v-if="error" role="alert" class="error">{{ error }}</p>
        <p v-if="notice" role="status" class="notice">{{ notice }}</p>
        <template v-if="!selected && !editing">
            <div class="tabs" role="tablist" :aria-label="isPrompt ? '模板来源' : 'Schema 来源'">
                <button
                    v-for="s in ['user', 'builtin']"
                    :key="s"
                    role="tab"
                    :aria-selected="source === s"
                    :class="{ active: source === s }"
                    @click="source = s"
                >
                    {{
                        s === 'user'
                            ? isPrompt
                                ? '我的模板'
                                : '我的 Schema'
                            : isPrompt
                              ? '内置模板'
                              : '内置 Schema'
                    }}
                    <span>{{ records.filter((r) => matchesSource(r, s)).length }}</span>
                </button>
            </div>
            <p class="scope" v-if="source === 'user'">
                包含我创建的资源和自定义流程实际使用的资源；同一资源只显示一次。
            </p>
            <div class="filters">
                <native-text v-model="search" :theme="theme" label="搜索资源" placeholder="搜索名称、描述或算子" />
                <native-select v-model="usage" :theme="theme" label="用途" :options="[{value:'',label:'全部用途'}, ...usages.map(u=>({value:u,label:u}))]" />
                <native-select v-model="purpose" :theme="theme" label="功能" :options="[{value:'',label:'全部功能'}, ...purposes.map(p=>({value:p,label:p}))]" />
                <native-select v-if="isPrompt" v-model="operator" :theme="theme" label="适用算子" :options="[{value:'',label:'全部算子'}, ...operators.map(o=>({value:o,label:o}))]" />
                <native-select v-model="pipeline" :theme="theme" label="Pipeline" :options="[{value:'',label:'全部 Pipeline'}, ...availablePipelines.map(p=>({value:p.id,label:p.name}))]" />
                <native-select v-if="pipeline" v-model="relation" :theme="theme" label="流程关系" :options="[{value:'referenced',label:'此流程使用'},{value:'compatible',label:'适用于此流程'}]" />
                <fv-button v-if="search || usage || purpose || pipeline || operator" :theme="theme" :border-radius="6" @click="clearFilters">清除筛选</fv-button>
            </div>
            <p v-if="pipeline" class="scope">
                {{
                    relation === 'compatible'
                        ? '按支持的算子匹配候选资源，变量绑定与执行条件仍需配置。'
                        : referenceScope
                }}
            </p>
            <section class="catalog">
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>名称</th>
                                <th>用途 / 功能</th>
                                <th>来源</th>
                                <th>使用情况</th>
                                <th>查看</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="r in filtered" :key="r.ref">
                                <td>
                                    <button class="name-link" @click="open(r)">{{ r.name }}</button>
                                </td>
                                <td>
                                    {{ r.usages.join(' · ') }}<small>{{ r.purpose }}</small>
                                </td>
                                <td>
                                    {{
                                        r.source === 'user'
                                            ? '自建'
                                            : source === 'user'
                                              ? '内置引用'
                                              : '内置'
                                    }}
                                </td>
                                <td>
                                    {{
                                        usageCount(r)
                                            ? usageCount(r) + ' 个自定义流程使用'
                                            : '尚未被自定义流程使用'
                                    }}
                                </td>
                                <td>
                                    <button
                                        class="link"
                                        @click="open(r)"
                                        :aria-label="`查看 ${r.name}`"
                                    >
                                        查看 →
                                    </button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <p v-if="!filtered.length" class="empty">
                    {{ loading ? '正在加载…' : '没有匹配的资源' }}
                </p>
            </section>
            <p class="scope">{{ filtered.length }} 项 · {{ referenceScope }}</p>
        </template>
        <section v-else class="detail">
            <fv-button :theme="theme" :border-radius="6"  class="link back" @click="back" :disabled="busy">
                ← 返回{{ isPrompt ? '模板' : 'Schema' }}列表
            </fv-button>
            <template v-if="editing">
                <h2>{{ editing.id ? '编辑' : '新建' }}{{ isPrompt ? '模板' : ' Schema' }}</h2>
                <form @submit.prevent="save">
                    <div class="form-grid">
                        <div class="native-field">名称<native-text v-model="editing.name" :theme="theme" :disabled="busy" label="名称" /></div>
                        <div class="native-field">用途<native-select v-model="editing.usage" :theme="theme" :disabled="busy" label="用途" :options="usages" /></div>
                        <div class="native-field">功能<native-select v-model="editing.purpose" :theme="theme" :disabled="busy" label="功能" :options="purposes" /></div>
                    </div>
                    <div class="native-field">描述<native-text v-model="editing.description" :theme="theme" :disabled="busy" label="描述" multiline :rows="2" /></div>
                    <template v-if="isPrompt">
                        <div class="native-field">模板内容<native-text v-model="editing.template" :theme="theme" :disabled="busy" label="模板内容" multiline code :rows="10" /></div>
                        <p class="help">使用 {变量名}；JSON 花括号可直接书写。文本清洗、QA、评分及图片问答按各自契约接入；必需变量和输出限制在算子参数中说明。</p>
                        <div class="native-field">允许的算子（可留空，不额外限制）<native-text v-model="allowedText" :theme="theme" :disabled="busy" label="允许的算子" placeholder="FormatStrPromptedGenerator, PromptedVQAGenerator" /></div>
                        <p class="help">检测到变量：{{ variablesOf(editing.template).join(' · ') || '无' }}</p>
                        <div class="native-field">预览变量（JSON 对象）<native-text v-model="exampleText" :theme="theme" :disabled="busy" label="预览变量" multiline code :rows="4" /></div>
                    </template>
                    <template v-else>
                        <div class="native-field">JSON Schema<native-text v-model="editing.schema" :theme="theme" :disabled="busy" label="JSON Schema" multiline code :rows="15" /></div>
                        <div class="native-field">示例数据<native-text v-model="editing.example" :theme="theme" :disabled="busy" label="示例数据" multiline code :rows="6" /></div>
                        <p class="help">只有被流程明确引用才会应用；保存 Schema 不会自动替换现有导入校验。</p>
                    </template>
                    <div class="actions">
                        <fv-button :theme="theme" :disabled="busy" :border-radius="6" @click="preview">{{ isPrompt ? '预览模板' : '校验 Schema 与示例' }}</fv-button>
                        <fv-button :theme="theme" :disabled="busy" :border-radius="6" @click="formatEditor">格式化 JSON</fv-button>
                        <fv-button theme="dark" background="#4e5bd5" :disabled="busy || !editing.name.trim() || editing.name.length > 240 || !(isPrompt ? editing.template.trim() : editing.schema.trim())" :border-radius="6" @click="save">保存</fv-button>
                        <fv-button :theme="theme" :disabled="busy" :border-radius="6" @click="cancelEdit">取消</fv-button>
                    </div>
                </form>
            </template>
            <template v-else-if="selected">
                <div class="detail-title">
                    <div>
                        <h2>{{ selected.name }}</h2>
                        <p>
                            {{ selected.source === 'builtin' ? '内置 · 只读' : '我的资源' }} ·
                            {{ selected.usages.join(' · ') }} · {{ selected.purpose }}
                        </p>
                    </div>
                    <div class="actions">
                        <fv-button :theme="theme" :border-radius="6"  v-if="!selected.readonly" @click="edit" :disabled="busy">编辑</fv-button><fv-button :theme="theme" :border-radius="6" v-if="!selected.readonly" @click="remove" :disabled="busy">
                            删除</fv-button><fv-button :theme="theme" :border-radius="6" v-if="selected.kind !== 'python'" @click="copyAsOwn">
                            复制为我的{{ isPrompt ? '模板' : ' Schema' }}</fv-button><fv-button :theme="theme" :border-radius="6" @click="copyContent">复制内容</fv-button>
                    </div>
                </div>
                <p v-if="selected.description" class="description">{{ selected.description }}</p>
                <dl>
                    <dt>资源引用</dt>
                    <dd>{{ selected.ref }}</dd>
                    <template v-if="isPrompt"
                        ><dt>适用算子</dt>
                        <dd>{{ selected.operators.join(' · ') || '未声明' }}</dd>
                        <dt v-if="selected.kind === 'python'">Python 类</dt>
                        <dd v-if="selected.kind === 'python'">{{ selected.id }}</dd>
                        <dt>变量 / 参数</dt>
                        <dd>{{ (selected.variables || []).join(' · ') || '无' }}</dd></template
                    ><template v-else
                        ><dt>必填字段</dt>
                        <dd>
                            {{ requiredFields(selected.schema).join(' · ') || '见下方 Schema' }}
                        </dd></template
                    >
                    <dt>更新时间</dt>
                    <dd>
                        {{
                            selected.source === 'builtin'
                                ? selected.version || '随代码维护'
                                : timeLabel(selected.updated_at)
                        }}
                    </dd>
                </dl>
                <template v-if="isPrompt && selected.kind === 'python'"
                    ><details open>
                        <summary>Python 源码与参数</summary>
                        <pre>{{ sourceCode || '正在加载源码…' }}</pre>
                        <pre>{{ JSON.stringify(selected.parameters, null, 2) }}</pre>
                    </details>
                    <p class="help">
                        Python
                        类可能包含条件和拼接逻辑。参数预览只生成提示词文本，不调用模型；预览结果另存后是固定文本，需要自行添加变量。
                    </p>
                    <div class="native-field">构造参数（JSON 对象）<native-text v-model="initText" :theme="theme" label="构造参数" multiline code :rows="3" /></div><div class="native-field"
                        >build_prompt 参数（JSON 对象）<native-text v-model="exampleText" :theme="theme" label="预览变量" multiline code :rows="4" />
                    </div>
                    <div class="actions">
                        <fv-button :theme="theme" :border-radius="6"  @click="preview" :disabled="busy">参数预览</fv-button><fv-button :theme="theme" :border-radius="6" v-if="previewText" @click="copyAsOwn">从预览新建文本模板</fv-button>
                    </div></template
                >
                <template v-else
                    ><h3>{{ isPrompt ? '模板内容' : 'JSON Schema' }}</h3>
                    <pre>{{ isPrompt ? selected.template : pretty(selected.schema) }}</pre>
                    <div class="native-field" v-if="isPrompt"
                        >预览变量（JSON 对象）<native-text v-model="exampleText" :theme="theme" label="预览变量" multiline code :rows="4" /></div><div class="native-field" v-else
                        >示例数据（可替换为待检查的数据）<native-text v-model="testExample" :theme="theme" label="示例数据" multiline code :rows="6" /></div><fv-button :theme="theme" :border-radius="6"  @click="preview" :disabled="busy">
                        {{ isPrompt ? '预览模板' : '校验示例' }}
                    </fv-button></template
                >
                <h3>使用流程、步骤与参数</h3>
                <ul v-if="visibleReferences.length" class="references">
                    <li v-for="(ref, i) in visibleReferences" :key="i">
                        <router-link :to="ref.route">{{ ref.pipeline_name }}</router-link> ·
                        {{ ref.step }} · {{ usageKind(ref.kind) }} · {{ ref.field }}
                        <small>{{
                            ref.pipeline_source === 'user' ? '自定义流程' : '内置流程'
                        }}</small>
                        <details>
                            <summary>查看此步骤的实际参数</summary>
                            <pre>{{ JSON.stringify(ref.parameters || {}, null, 2) }}</pre>
                            <p v-if="ref.evidence" class="help">用法依据：{{ ref.evidence }}</p>
                        </details>
                        <pre v-if="Object.keys(ref.bindings).length">{{
                            JSON.stringify(ref.bindings, null, 2)
                        }}</pre>
                    </li>
                </ul>
                <p v-else class="help">当前已保存流程中没有已确认的使用记录。</p>
                <p class="help">{{ referenceScope }}</p>
            </template>
            <section v-if="previewText || previewError" class="preview">
                <h3>{{ isPrompt ? '渲染预览' : '校验结果' }}</h3>
                <p v-if="previewError" role="alert" class="error">{{ previewError }}</p>
                <pre v-if="previewText">{{ previewText }}</pre>
            </section>
        </section>
    </main>
</template>
<script>
import axios from 'axios'
import { mapState } from 'pinia'
import { useTheme } from '@/stores/theme'
import {
    usages,
    pipelineOptions,
    filterResources,
    timeLabel,
    variablesOf,
    matchesPipeline,
    matchesSource,
    usageCount,
    usageKind
} from './catalog.js'
import {filtersFromQuery,queryForFilters} from './resourceQuery'
import NativeSelect from '@/components/manage/forms/NativeSelect.vue'
import NativeText from '@/components/manage/forms/NativeText.vue'
import { publishChange, subscribeChanges } from '@/components/manage/forms/changes'

import { useUnsavedChanges, confirmDiscard } from '@/components/manage/forms/unsaved'

export default {
    setup(){useUnsavedChanges(vm=>vm.editDirty,vm=>{vm.editing=null})},
    components: { NativeSelect, NativeText },
    name: 'ManagedResourceCatalog',
    props: { kind: { type: String, required: true } },
    data: () => ({
        records: [],
        pipelines: [],
        referenceScope: '',
        source: 'user',
        search: '',
        usage: '',
        purpose: '',
        pipeline: '',
        operator: '',
        relation: 'referenced',
        selected: null,
        editing: null, editBaseline: '',
        busy: false,
        loading: false,
        error: '',
        notice: '',
        sourceCode: '',
        previewText: '',
        previewError: '',
        exampleText: '{}',
        initText: '{}',
        allowedText: '',
        testExample: '',
        requestVersion: 0,
        applyingQuery: false, syncPending: false, stopChanges: null,
        usages
    }),
    computed: {
        editDirty(){return !!this.editing && this.editBaseline!==JSON.stringify([this.editing,this.exampleText,this.allowedText])},
        filterState() { return [this.source,this.search,this.usage,this.purpose,this.pipeline,this.operator,this.relation] },
        visibleReferences() {
            return (this.selected?.references || []).filter((ref) =>
                this.pipeline
                    ? matchesPipeline(ref, this.pipeline, this.availablePipelines)
                    : this.source !== 'user' || ref.pipeline_source === 'user'
            )
        },
        availablePipelines() {
            return pipelineOptions(this.pipelines, this.source)
        },
        ...mapState(useTheme, ['theme']),
        isPrompt() {
            return this.kind === 'prompt'
        },
        base() {
            return this.isPrompt ? '/prompts' : '/json_schemas'
        },
        purposes() {
            return this.isPrompt
                ? ['通用', '生成', '清洗', '评分']
                : ['通用', '模型输出', '训练样本校验']
        },
        operators() {
            return [...new Set(this.records.flatMap((r) => r.operators))].sort()
        },
        filtered() {
            return filterResources(this.records, this, this.availablePipelines)
        }
    },
    watch: {
        filterState: { deep:true, handler() { if (!this.applyingQuery) this.syncQuery() } },
        source() {
            this.ensurePipeline()
        },
        '$route.query': {
            deep: true,
            handler() {
                this.applyQuery()
            }
        },
        kind() {
            this.selected=null;this.editing=null;this.previewText='';this.previewError='';this.error='';this.notice='';this.syncPending=false
            this.applyQuery();this.load()
        }
    },
    mounted() {
        this.stopChanges = subscribeChanges(change => { if (['resources','pipelines'].includes(change.topic)) { if(this.editing || this.busy)this.syncPending=true;else this.load() } })
        this.load()
    },
    activated() {
        this.load()
    },
    beforeUnmount() { this.stopChanges?.() },
    methods: {
        matchesPipeline,
        matchesSource,
        usageCount,
        usageKind,
        timeLabel,
        variablesOf,
        async request(method, path, data) {
            const res = await axios({ method, url: '/api/v1' + path, data })
            if (!res.data.success) throw new Error(res.data.message)
            return res.data.data
        },
        async action(fn) {
            if (this.busy) return
            this.busy = true
            this.error = ''
            this.notice = ''
            try {
                await fn()
            } catch (e) {
                this.error = e.response?.data?.message || e.message
            } finally {
                this.busy = false
            }
        },
        async load() {
            const version = ++this.requestVersion
            this.loading = true
            try {
                const result = await this.request('get', this.base + '/catalog')
                if (version !== this.requestVersion) return
                this.records = result.resources
                this.pipelines = result.pipelines
                this.referenceScope = result.reference_scope
                if (this.selected) {
                    const previous=this.selected
                    this.selected=this.records.find(r=>r.ref===previous.ref)||null
                    if(this.selected && !this.editing && this.selected.updated_at!==previous.updated_at){this.exampleText=JSON.stringify(this.selected.example_variables||{},null,2);this.testExample=this.selected.example||'';this.previewText='';this.previewError=''}
                }
                this.applyQuery()
            } catch (e) {
                if (version === this.requestVersion)
                    this.error = e.response?.data?.message || e.message
            } finally {
                if (version === this.requestVersion) this.loading = false
            }
        },
        ensurePipeline() {
            if (!this.pipeline) return
            const selected = this.availablePipelines.find(
                (p) => p.id === this.pipeline || p.member_ids?.includes(this.pipeline)
            )
            this.pipeline = selected?.id || ''
        },
        syncQuery() {
            if (this.$route.path !== (this.isPrompt ? '/m/prompts' : '/m/schemas')) return
            const query = queryForFilters(this.$route.query,this)
            if (JSON.stringify(Object.entries(query).sort()) !== JSON.stringify(Object.entries(this.$route.query).sort())) return this.$router.replace({path:this.$route.path,query})
        },
        applyQuery() {
            if (this.$route.path !== (this.isPrompt ? '/m/prompts' : '/m/schemas')) return
            const q = this.$route.query
            if (!q.resource && this.selected && !this.editing) this.selected = null
            this.applyingQuery = true
            Object.assign(this,filtersFromQuery(q))
            this.$nextTick(() => { this.applyingQuery = false })
            this.ensurePipeline()
            if (q.resource && !this.editing) {
                const row = this.records.find((r) => r.ref === q.resource)
                if (row) {
                    if (!matchesSource(row, this.source)) this.source = row.source
                    if (this.selected?.ref !== row.ref) this.open(row, false)
                }
            }
        },
        clearFilters() {
            this.search = ''
            this.usage = ''
            this.purpose = ''
            this.pipeline = ''
            this.operator = ''
            this.relation = 'referenced'
            if (Object.keys(this.$route.query).length)
                this.$router.replace({ path: this.$route.path, query: {} })
        },
        async back() {
            if(this.editDirty && !await confirmDiscard(this))return false
            this.selected = null
            this.editing = null
            this.previewText = ''
            this.previewError = ''
            if (this.$route.query.resource) {
                const query = { ...this.$route.query }
                delete query.resource
                this.$router.replace({ path: this.$route.path, query })
            }
        },
        async open(row, route = true) {
            this.selected = row
            this.editing = null
            this.previewText = ''
            this.previewError = ''
            this.sourceCode = ''
            this.exampleText = JSON.stringify(row.example_variables || {}, null, 2)
            this.testExample = row.example || ''
            this.initText = '{}'
            if (route)
                this.$router.replace({
                    path: this.$route.path,
                    query: { ...this.$route.query, resource: row.ref }
                })
            if (row.kind === 'python') {
                try {
                    const result = await this.request(
                        'get',
                        '/prompts/source/' + encodeURIComponent(row.id)
                    )
                    if (this.selected?.ref === row.ref) this.sourceCode = result.source
                } catch (e) {
                    this.error = e.message
                }
            }
        },
        form(record = {}) {
            return {
                name: '',
                description: '',
                usage: '通用',
                purpose: '通用',
                template: '',
                schema: '',
                example: '',
                ...JSON.parse(JSON.stringify(record))
            }
        },
        async create() {
            if(await this.back()===false)return
            this.selected = null
            this.source = 'user'
            this.editing = this.form()
            this.exampleText = '{}'
            this.allowedText = ''
            this.previewText = ''
            this.previewError = ''
            this.editBaseline=JSON.stringify([this.editing,this.exampleText,this.allowedText])
        },
        edit() {
            this.editing = this.form({ ...this.selected, usage: this.selected.usages[0] })
            this.allowedText = (this.selected.allowed_operators || []).join(', ')
            this.exampleText = JSON.stringify(this.selected.example_variables || {}, null, 2)
            this.previewText = ''
            this.previewError = ''
            this.editBaseline=JSON.stringify([this.editing,this.exampleText,this.allowedText])
        },
        async copyAsOwn() {
            const row = this.selected,
                rendered = this.previewText
            if(await this.back()===false)return
            this.editing = this.form({
                ...row,
                id: undefined,
                name: row.name + '（副本）',
                usage: row.usages[0],
                template: row.kind === 'python' ? rendered : row.template
            })
            this.selected = null
            this.source = 'user'
            this.allowedText = (
                row.kind === 'python'
                    ? ['FormatStrPromptedGenerator']
                    : row.allowed_operators || row.operators || []
            ).join(', ')
            this.exampleText = JSON.stringify(row.example_variables || {}, null, 2)
            this.previewText = ''
            this.previewError = ''
            this.editBaseline=JSON.stringify([this.editing,this.exampleText,this.allowedText])
        },
        async cancelEdit() {
            if (this.busy || this.editDirty && !await confirmDiscard(this)) return
            this.editing = null
            if(this.syncPending){this.syncPending=false;this.load()}
            this.previewText = ''
            this.previewError = ''
        },
        object(text) {
            const result = JSON.parse(text)
            if (!result || typeof result !== 'object' || Array.isArray(result))
                throw new Error('参数必须是 JSON 对象')
            return result
        },
        async save() {
            await this.action(async () => {
                const r = this.editing, kind = this.kind, base = this.base
                if (!r || !r.name.trim() || r.name.length > 240) throw new Error('请填写 1–240 字名称')
                const payload = {
                    ...(r.id ? {expected_updated_at:r.updated_at} : {}),
                    name: r.name,
                    description: r.description,
                    usage: r.usage,
                    purpose: r.purpose,
                    ...(this.isPrompt
                        ? {
                              template: r.template,
                              allowed_operators: this.allowedText
                                  .split(/[,，]/)
                                  .map((s) => s.trim())
                                  .filter(Boolean),
                              example_variables: this.object(this.exampleText)
                          }
                        : { schema: r.schema, example: r.example })
                }
                const saved = await this.request(
                    r.id ? 'put' : 'post',
                    base +
                        (kind === 'prompt' ? '/user' : '') +
                        (r.id ? '/' + encodeURIComponent(r.id) : ''),
                    payload
                )
                publishChange('resources', saved.id)
                if(this.kind !== kind || this.editing !== r)return
                this.editing = null
                this.syncPending = false
                this.source = 'user'
                await this.syncQuery()
                await this.load()
                this.source = 'user'
                const row = this.records.find(
                    (item) => item.id === saved.id && item.source === 'user'
                )
                if (row) await this.open(row)
                this.notice = '已保存'
            })
        },
        async remove() {
            const selected=this.selected, kind=this.kind, base=this.base
            if(!selected || !window.confirm(`删除“${selected.name}”？已有任务快照保持原样。`))return
            await this.action(async()=>{
                await this.request('delete',base+(kind==='prompt'?'/user':'')+'/'+encodeURIComponent(selected.id))
                publishChange('resources',selected.id)
                if(this.kind!==kind || this.selected?.ref!==selected.ref)return
                this.back();this.syncPending=false;await this.load();this.notice='已删除'
            })
        },
        async preview() {
            if (this.busy) return
            this.busy = true
            this.previewText = ''
            this.previewError = ''
            const kind=this.kind, target=this.editing || this.selected
            try {
                const r = target
                if (this.isPrompt) {
                    const result =
                        this.selected?.kind === 'python' && !this.editing
                            ? await this.request('post', '/prompts/builtin-preview', {
                                  name: r.id,
                                  init: this.object(this.initText),
                                  variables: this.object(this.exampleText)
                              })
                            : await this.request('post', '/prompts/user/preview', {
                                  template: r.template,
                                  variables: this.object(this.exampleText)
                              })
                    if(this.kind!==kind || (this.editing || this.selected)!==target)return
                    this.previewText = result.rendered
                    if (result.missing?.length)
                        this.previewError = '缺少变量：' + result.missing.join('、')
                } else {
                    await this.request('post', '/json_schemas/validate', {
                        name: r.name || '校验',
                        schema: r.schema,
                        example: this.editing ? r.example : this.testExample
                    })
                    if(this.kind!==kind || (this.editing || this.selected)!==target)return
                    this.previewText =
                        'Schema 有效' +
                        ((this.editing ? r.example : this.testExample)?.trim()
                            ? '，示例校验通过。'
                            : '。尚未提供示例数据。')
                }
            } catch (e) {
                if(this.kind===kind && (this.editing || this.selected)===target)this.previewError = e.response?.data?.message || e.message
            } finally {
                this.busy = false
                if(this.syncPending && !this.editing){this.syncPending=false;this.load()}
            }
        },
        pretty(value) {
            try {
                return JSON.stringify(
                    typeof value === 'string' ? JSON.parse(value) : value,
                    null,
                    2
                )
            } catch {
                return value
            }
        },
        schemaFields(value) {
            try {
                const r = typeof value === 'string' ? JSON.parse(value) : value
                return [
                    ...new Set([
                        ...Object.keys(r.properties || {}),
                        ...(r.allOf || []).flatMap((s) => Object.keys(s.properties || {})),
                        ...(r.anyOf || []).flatMap((s) => Object.keys(s.properties || {}))
                    ])
                ]
            } catch {
                return []
            }
        },
        requiredFields(value) {
            try {
                const r = JSON.parse(value)
                return [
                    ...new Set([
                        ...(r.required || []),
                        ...(r.allOf || []).flatMap((s) => s.required || [])
                    ])
                ]
            } catch {
                return []
            }
        },
        formatEditor() {
            try {
                if (this.isPrompt)
                    this.exampleText = JSON.stringify(this.object(this.exampleText), null, 2)
                else {
                    this.editing.schema = JSON.stringify(JSON.parse(this.editing.schema), null, 2)
                    if (this.editing.example.trim())
                        this.editing.example = JSON.stringify(
                            JSON.parse(this.editing.example),
                            null,
                            2
                        )
                }
            } catch (e) {
                this.error = e.message
            }
        },
        async copyContent() {
            try {
                await navigator.clipboard.writeText(
                    this.sourceCode ||
                        (this.isPrompt ? this.selected.template : this.selected.schema)
                )
                this.notice = '已复制内容'
            } catch (e) {
                this.error = e.message
            }
        }
    }
}
</script>
<style scoped>
.native-field{display:block;margin-bottom:18px;line-height:2}.filters>*{min-width:150px;flex:1}.filters>:first-child{min-width:220px}
.resources {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    flex: 1;
    min-width: 0;
    overflow: auto;
    padding: 28px;
    color: #25334c;
    background: #f7f8fb;
    font-size: 14px;
}
header,
.detail-title,
.actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}
header {
    margin-bottom: 24px;
    flex-wrap: wrap;
}
h1 {
    font-size: 25px;
    margin: 0 0 8px;
}
h2 {
    font-size: 20px;
    margin: 0 0 8px;
}
h3 {
    font-size: 15px;
    margin: 24px 0 10px;
}
p {
    line-height: 1.7;
    margin: 0;
}
header p,
.detail-title p,
.help,
.scope {
    color: #78849a;
    font-size: 12px;
}
.actions {
    justify-content: flex-end;
    flex-wrap: wrap;
}
button,
input,
select,
textarea {
    font: inherit;
    color: inherit;
    border: 1px solid #d9dfeb;
    border-radius: 8px;
    background: white;
    padding: 9px 12px;
    box-sizing: border-box;
}
button {
    cursor: pointer;
}
button:disabled {
    opacity: 0.5;
    cursor: default;
}
.primary {
    background: #4e5bd5;
    border-color: #4e5bd5;
    color: white;
}
.tabs {
    display: flex;
    gap: 8px;
    border-bottom: 1px solid #e2e7f0;
    margin-bottom: 18px;
}
.tabs button {
    border: 0;
    background: transparent;
    padding: 12px 18px;
}
.tabs .active {
    background: white;
    color: #4e5bd5;
    font-weight: 600;
}
.tabs span {
    padding: 2px 7px;
    background: #e9edf6;
    border-radius: 12px;
    margin-left: 6px;
}
.filters {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 18px;
}
.filters input {
    flex: 1;
    min-width: 190px;
    max-width: 400px;
}
.filters select {
    max-width: 260px;
}
.catalog,
.detail {
    border: 1px solid #e2e7f0;
    border-radius: 12px;
    background: white;
    overflow: hidden;
}
.detail {
    padding: 24px;
}
.table-scroll {
    overflow: auto;
}
table {
    border-collapse: collapse;
    width: 100%;
    text-align: left;
}
th {
    background: #fafbfe;
    color: #78849a;
    font-size: 12px;
    font-weight: 500;
}
th,
td {
    padding: 16px 20px;
    border-bottom: 1px solid #edf0f5;
}
td:first-child {
    width: 30%;
    min-width: 200px;
}
td:nth-child(3) {
    max-width: 350px;
    overflow-wrap: anywhere;
}
td:nth-last-child(2) {
    font-size: 12px;
    white-space: nowrap;
}
small {
    display: block;
    font-size: 12px;
    color: #78849a;
    margin-top: 5px;
}
.name-link,
.link {
    padding: 0;
    border: 0;
    background: transparent;
    color: #4e5bd5;
    text-align: left;
}
.name-link {
    font-weight: 600;
    overflow-wrap: anywhere;
}
.back {
    width: max-content;
    min-width: 180px;
    white-space: nowrap;
    margin-bottom: 24px;
}
.empty {
    padding: 40px;
    text-align: center;
    color: #78849a;
}
.scope {
    margin: 12px 0;
}
.error,
.notice {
    padding: 12px;
    border-radius: 8px;
    margin-bottom: 16px;
    overflow-wrap: anywhere;
}
.error {
    color: #a43028;
    background: #fff0ed;
}
.notice {
    color: #306448;
    background: #e9f4ed;
}
label {
    display: block;
    line-height: 1.8;
    margin: 16px 0;
}
label input,
label select,
label textarea {
    display: block;
    width: 100%;
    margin-top: 6px;
}
textarea {
    resize: vertical;
    font-family: ui-monospace, monospace;
    font-size: 13px;
    line-height: 1.7;
}
.form-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr;
    gap: 16px;
}
.description {
    margin: 18px 0;
    white-space: pre-wrap;
}
dl {
    display: grid;
    grid-template-columns: 110px minmax(0, 1fr);
    gap: 12px;
    font-size: 13px;
}
dt {
    color: #78849a;
}
dd {
    margin: 0;
    overflow-wrap: anywhere;
}
pre {
    background: #f7f8fb;
    padding: 16px;
    border-radius: 8px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 500px;
    overflow: auto;
    font-size: 12px;
    line-height: 1.8;
}
summary {
    cursor: pointer;
}
.references {
    padding-left: 20px;
    line-height: 2;
}
a {
    color: #4e5bd5;
}
.dark {
    background: #20242d;
    color: #dfe5ef;
}
.dark .catalog,
.dark .detail,
.dark input,
.dark select,
.dark textarea,
.dark button {
    background: #292e39;
    color: inherit;
    border-color: #424b5b;
}
.dark th,
.dark pre {
    background: #252a35;
}
.dark td,
.dark th,
.dark .tabs {
    border-color: #424b5b;
}
.dark .tabs .active {
    background: #343f66;
}
.dark button.primary {
    background: #4e5bd5;
}
.dark .link,
.dark .name-link {
    color: #aab7ff;
    background: transparent;
}
.dark .error {
    background: #4e2929;
    color: #ffc3bb;
}
.dark .notice {
    background: #244032;
    color: #c1e6ce;
}
@media (max-width: 850px) {
    .resources {
        padding: 16px;
    }
    .detail {
        padding: 16px;
    }
    .form-grid {
        grid-template-columns: 1fr;
    }
    .detail-title {
        align-items: flex-start;
        flex-wrap: wrap;
    }
    th,
    td {
        padding: 12px;
    }
    .filters select {
        max-width: 100%;
    }
}
</style>
