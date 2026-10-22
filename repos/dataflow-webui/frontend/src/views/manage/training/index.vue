<template>
    <main class="training" :class="{ dark: theme === 'dark' }">
        <header>
            <div>
                <h1>模型训练</h1>
                <p>配置 DataFlex 训练方案，固定数据与运行输入。</p>
            </div>
            <div class="actions">
                <button :disabled="busy" @click="load">刷新列表</button
                ><button :disabled="busy" @click="newPlan">新建方案</button>
            </div>
        </header>
        <p class="error" role="alert" v-if="error">{{ error }}</p>
        <p role="status">{{ notice }}</p>
        <section v-if="!record">
            <h2>训练方案</h2>
            <p v-if="!plans.length">还没有训练方案。普通训练无需创建实验组。</p>
            <button class="row" v-for="r in plans" :key="r.id" @click="open(r.id)">
                <strong>{{ r.plan.name }}</strong
                ><span
                    >{{ r.plan.model || '模型待填写' }} · {{ r.plan.strategy.family }} · v{{
                        r.version
                    }}</span
                >
            </button>
        </section>
        <template v-else
            ><nav>
                <button @click="close">← 方案列表</button
                ><span>版本 {{ record.version || '未保存' }}</span>
            </nav>
            <section>
                <h2>模型与预算</h2>
                <div class="grid">
                    <label
                        >方案名称<native-text
                            v-model="record.plan.name"
                            :theme="theme"
                            label="方案名称" /></label
                    ><label
                        >模型引用<native-text
                            v-model="record.plan.model"
                            :theme="theme"
                            label="模型引用"
                            placeholder="远端模型路径或固定模型 ID" /></label
                    ><label
                        >Tokenizer（留空沿用模型）<native-text
                            v-model="record.plan.tokenizer"
                            :theme="theme"
                            label="Tokenizer" /></label
                    ><label
                        >模型 revision<native-text
                            v-model="record.plan.model_revision"
                            :theme="theme"
                            label="模型 revision" /></label
                    ><label
                        >任务<native-select
                            v-model="record.plan.task"
                            :options="['sft', 'pt', 'dpo']"
                            :theme="theme"
                            label="训练任务" /></label
                    ><label
                        >模态<native-select
                            v-model="record.plan.modality"
                            :options="['text', 'image_text']"
                            :theme="theme"
                            label="模态" /></label
                    ><label
                        >微调方式<native-select
                            v-model="record.plan.finetuning_type"
                            :options="['lora', 'full']"
                            :theme="theme"
                            label="微调方式" /></label
                    ><label
                        >模板<native-text
                            v-model="record.plan.template"
                            :theme="theme"
                            label="模型模板" /></label
                    ><label
                        v-for="k in [
                            'max_steps',
                            'batch_size',
                            'gradient_accumulation_steps',
                            'learning_rate',
                            'seed'
                        ]"
                        :key="k"
                        >{{ labels[k]
                        }}<input
                            type="number"
                            :step="k === 'learning_rate' ? 'any' : '1'"
                            v-model.number="record.plan[k]"
                            :aria-label="labels[k]"
                    /></label>
                </div>
            </section>
            <section>
                <h2>数据绑定</h2>
                <p>
                    仅引用已发布版本。草稿请先在<router-link to="/m/training-datasets"
                        >生成数据集</router-link
                    >明确发布。保存配置不会下载数据或模型。
                </p>
                <article v-for="(b, i) in record.plan.data" :key="i">
                    <div class="grid">
                        <label
                            >角色<native-select
                                v-model="b.role"
                                :options="roles"
                                :theme="theme"
                                label="数据角色" /></label
                        ><label
                            >来源<native-select
                                v-model="b.kind"
                                :options="kinds"
                                :theme="theme"
                                label="数据来源" /></label
                        ><label
                            >域<native-text
                                v-model="b.domain"
                                :theme="theme"
                                label="数据域" /></label
                        ><label v-if="b.kind === 'release'"
                            >发布版本<native-select
                                v-model="b.ref"
                                :options="releaseOptions"
                                :theme="theme"
                                label="发布版本" /></label
                        ><label v-else
                            >路径或数据集 ID<native-text
                                v-model="b.ref"
                                :theme="theme"
                                label="数据引用" /></label
                        ><label v-if="b.kind === 'huggingface'"
                            >固定 revision<native-text
                                v-model="b.revision"
                                :theme="theme"
                                label="数据 revision" /></label
                        ><label v-if="b.kind === 'huggingface'"
                            >子集<native-text
                                v-model="b.subset"
                                :theme="theme"
                                label="子集" /></label
                        ><label v-if="b.kind === 'huggingface'"
                            >划分<native-text
                                v-model="b.split"
                                :theme="theme"
                                label="数据划分" /></label
                        ><label v-if="b.kind === 'file'"
                            >期望 SHA-256（可留空，导出时固定）<native-text
                                v-model="b.sha256"
                                :theme="theme"
                                label="数据哈希"
                        /></label>
                    </div>
                    <button @click="record.plan.data.splice(i, 1)">移除此绑定</button>
                </article>
                <button @click="addBinding">添加数据绑定</button>
            </section>
            <section>
                <h2>实验组（可选）</h2>
                <native-select
                    v-model="record.plan.group_id"
                    :options="[
                        { value: null, label: '独立训练' },
                        ...groups.map((g) => ({ value: g.id, label: g.name }))
                    ]"
                    :theme="theme"
                    label="实验组"
                />
                <details>
                    <summary>新建实验组</summary>
                    <label
                        >名称<native-text
                            v-model="groupName"
                            :theme="theme"
                            label="实验组名称" /></label
                    ><label
                        >共享条件（JSON）<native-text
                            v-model="groupShared"
                            multiline
                            code
                            :rows="3"
                            :theme="theme"
                            label="实验组共享条件" /></label
                    ><label
                        >允许差异字段（逗号分隔）<native-text
                            v-model="groupAllowed"
                            :theme="theme"
                            label="允许差异字段" /></label
                    ><button @click="addGroup">创建实验组</button>
                </details>
            </section>
            <section>
                <h2>数据策略</h2>
                <div class="grid">
                    <label
                        >策略类别<native-select
                            :model-value="record.plan.strategy.family"
                            @update:modelValue="setFamily"
                            :options="families"
                            :theme="theme"
                            label="策略类别" /></label
                    ><label v-if="record.plan.strategy.family !== 'static'"
                        >组件<native-select
                            :model-value="record.plan.strategy.component"
                            @update:modelValue="setComponent"
                            :options="componentOptions"
                            :theme="theme"
                            label="策略组件"
                    /></label>
                </div>
                <p v-if="selectedComponent">
                    源码 {{ selectedComponent.source_commit || '自定义' }} ·
                    {{ selectedComponent.validation }}。可编辑配置不代表算法已经实机验证。
                </p>
                <parameter-fields
                    v-if="selectedComponent"
                    v-model="record.plan.strategy.params"
                    :fields="
                        Object.fromEntries(
                            Object.entries(selectedComponent.fields).filter(([k]) => k !== 'stages')
                        )
                    "
                    :theme="theme"
                    @invalid="parameterInvalid = $event"
                />
                <div v-if="record.plan.strategy.family !== 'static'" class="grid">
                    <label v-for="k in ['update_step', 'update_times', 'warmup_step']" :key="k"
                        >{{ k }}<input type="number" v-model.number="record.plan.strategy[k]"
                    /></label>
                </div>
                <lego-stages
                    v-if="record.plan.strategy.family === 'lego' && selectedComponent"
                    :model-value="
                        record.plan.strategy.params.stages ||
                        selectedComponent.defaults.stages ||
                        []
                    "
                    @update:modelValue="record.plan.strategy.params.stages = $event"
                    :components="components"
                    :theme="theme"
                />
                <p v-if="record.plan.strategy.family === 'lego'">
                    阶段列表与高级 JSON 共用配置，顺序为 selector → mixer → reorder →
                    weighter。每阶段可填写组件、频率与 keep_ratio；检查会拒绝不兼容组合。
                </p>
                <button
                    :disabled="busy || !record.id || hasPending || parameterInvalid"
                    @click="compile"
                >
                    生成配置预览
                </button>
                <details v-if="compiled">
                    <summary>运行专用配置</summary>
                    <template v-for="(text, name) in compiled.yaml" :key="name"
                        ><h3>{{ name }}</h3>
                        <pre>{{ text }}</pre>
                    </template>
                </details>
                <details>
                    <summary>算法清单与扩展描述</summary>
                    <p>
                        描述只生成表单；实现需在独立 DataFlex 源码中注册。当前训练服务不会导入任意
                        Python。
                    </p>
                    <table>
                        <thead>
                            <tr>
                                <th>组件</th>
                                <th>任务/模态</th>
                                <th>准备条件</th>
                                <th>状态</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="c in components" :key="c.id">
                                <td>{{ c.id }}</td>
                                <td>{{ c.tasks.join('/') }} · {{ c.modalities.join('/') }}</td>
                                <td>{{ c.prerequisites?.join('；') || '按运行环境预检' }}</td>
                                <td>{{ c.validation }}</td>
                            </tr>
                        </tbody>
                    </table>
                    <native-text
                        v-model="descriptorText"
                        multiline
                        code
                        :rows="10"
                        :theme="theme"
                        label="自定义组件描述 JSON"
                    /><button @click="addDescriptor">注册描述</button>
                </details>
            </section>
            <section>
                <div class="actions">
                    <button class="primary" :disabled="busy || parameterInvalid" @click="save">
                        保存方案</button
                    ><button :disabled="busy || !record.id" @click="copy">复制已保存版本</button
                    ><button :disabled="busy || !record.id || hasPending" @click="check">
                        检查运行条件
                    </button>
                </div>
                <p v-if="hasPending">有未保存修改。</p>
                <template v-if="checks"
                    ><p>
                        结构：{{ checks.structure }} · 参数语义：{{
                            checks.parameter_semantics || '基础结构'
                        }}
                        · 数据/组件：{{ checks.compatibility }} · 环境：{{ checks.environment }} ·
                        真实训练：{{ checks.runtime }}
                    </p>
                    <ul>
                        <li v-for="e in checks.errors" :key="e">{{ e }}</li>
                    </ul>
                    <ul>
                        <li v-for="w in checks.warnings" :key="w">{{ w }}</li>
                    </ul></template
                >
            </section>
            <section>
                <h2>运行包</h2>
                <p>数据与执行源码随包固定；模型权重不包含在内。导出不启动训练。</p>
                <button :disabled="busy || !record.id || hasPending" @click="makeBundle">
                    生成运行包
                </button>
                <article
                    v-for="b in bundles.filter((b) => b.manifest.plan_id === record.id)"
                    :key="b.id"
                >
                    <strong>{{ b.id }}</strong>
                    <p>
                        方案版本 {{ b.manifest.plan_version }} · 源码
                        {{ b.manifest.source.commit }} ·
                        {{ b.manifest.source.dirty ? '有未提交源码' : '已提交源码' }}
                    </p>
                    <p>输入清单 SHA-256：{{ b.manifest_sha256 }}</p>
                    <a :href="'/api/v1/training/bundles/' + b.id + '/download'" download>下载 ZIP</a
                    ><button :disabled="busy || !host" @click="startBundle(b)">
                        在固定主机启动
                    </button>
                    <p v-if="!host">未配置训练主机，启动不可用。</p>
                    <details>
                        <summary>文件与引用清单</summary>
                        <pre>{{ b.manifest }}</pre>
                    </details>
                </article>
            </section>
            <details>
                <summary>高级配置（保留未知字段）</summary>
                <native-text
                    :model-value="advancedText"
                    @update:modelValue="editAdvanced"
                    multiline
                    code
                    :rows="14"
                    :theme="theme"
                    label="高级配置 JSON"
                /><button @click="applyAdvanced">应用 JSON 到表单</button
                ><button @click="syncAdvanced">从表单更新 JSON</button>
                <p v-if="advancedEdited">
                    高级 JSON 尚未应用，请应用到表单，或从表单更新以放弃这段修改。
                </p>
            </details>
        </template>
        <section>
            <h2>导入运行包</h2>
            <p>导入在独立环境物化数据后的派生包，核验清单和成员哈希。不会执行包内代码。</p>
            <label
                >运行包 ZIP<input type="file" accept=".zip" :disabled="busy" @change="uploadBundle"
            /></label>
        </section>
        <section>
            <h2>本地训练备份</h2>
            <p>覆盖方案、主机/运行元数据、运行包和轻量结果；远端模型 checkpoint 不包含在内。</p>
            <button :disabled="busy" @click="backupTraining">创建可核验备份</button
            ><a
                v-if="backupId"
                :href="'/api/v1/training/backups/' + backupId + '/download'"
                download
                >下载训练备份</a
            >
        </section>
        <section>
            <h2>固定训练主机</h2>
            <p>复用系统 SSH config 和 known_hosts；不在页面接收私钥。真实 SSH/GPU 验收尚未进行。</p>
            <p v-if="!host">尚未配置主机；保存方案与导出可用，启动不可用。</p>
            <details>
                <summary>主机设置</summary>
                <div class="grid">
                    <label v-for="k in ['alias', 'workdir', 'python', 'gpus']" :key="k"
                        >{{
                            {
                                alias: 'SSH alias',
                                workdir: '远端工作目录',
                                python: '训练环境 Python 绝对路径',
                                gpus: 'GPU 编号'
                            }[k]
                        }}<native-text v-model="hostForm[k]" :theme="theme" :label="'主机 ' + k"
                    /></label>
                </div>
                <button :disabled="busy" @click="saveHost">保存固定主机</button
                ><button :disabled="busy || !host" @click="probeHost">只读检查环境</button>
                <pre v-if="hostProbe">{{ hostProbe }}</pre>
            </details>
            <article v-for="c in controls" :key="c.id">
                <strong>{{ c.id }} · {{ c.phase }}</strong>
                <p>连接 {{ c.connection }} · 最后观测 {{ c.last_observed_at }}</p>
                <p v-if="c.error" role="alert">{{ c.error }}</p>
                <div class="actions">
                    <button :disabled="busy" @click="control(c, 'sync')">同步状态与结果</button
                    ><button
                        :disabled="busy || ['completed', 'failed', 'stopped'].includes(c.phase)"
                        @click="control(c, 'stop')"
                    >
                        核验身份并停止</button
                    ><button
                        :disabled="busy || !['completed', 'failed', 'stopped'].includes(c.phase)"
                        @click="rerun(c)"
                    >
                        从头重跑（新 attempt）
                    </button>
                </div>
            </article>
        </section>
        <section>
            <h2>运行记录与结果</h2>
            <p>只有执行或导入结果才产生记录。合成夹具单独标记，默认不进入真实比较。</p>
            <details>
                <summary>导入轻量结果 JSON</summary>
                <native-text
                    v-model="resultText"
                    multiline
                    code
                    :rows="10"
                    :theme="theme"
                    label="结果 JSON"
                /><button :disabled="busy" @click="importResult">导入结果</button>
            </details>
            <label><input type="checkbox" v-model="includeSynthetic" /> 比较时包含合成夹具</label
            ><button :disabled="busy || compareIds.length < 2" @click="compareRuns">
                比较所选运行
            </button>
            <article v-for="r in runs" :key="r.id">
                <label
                    ><input type="checkbox" v-model="compareIds" :value="r.id" />{{
                        r.synthetic ? '合成夹具 · ' : ''
                    }}{{ r.plan_snapshot.name }} · {{ r.status }} · attempt {{ r.id }}</label
                ><button @click="openRun(r.id)">查看运行详情</button>
            </article>
            <p v-if="!runs.length">尚无运行记录。</p>
        </section>
        <section v-if="run">
            <h2>{{ run.synthetic ? '合成夹具 · ' : '' }}运行详情 · {{ run.status }}</h2>
            <p>run {{ run.run_id }} / attempt {{ run.id }} · 序号 {{ run.sequence }}</p>
            <p v-if="run.result.error" role="alert">{{ run.result.error }}</p>
            <metric-chart :rows="run.result.metrics" :theme="theme" />
            <h3>策略信号</h3>
            <metric-chart
                :rows="run.result.strategy_metrics || []"
                kind="strategy"
                :theme="theme"
            />
            <p>资源、token、耗时指标仅展示实际提供的值；缺失表示未提供。</p>
            <details>
                <summary>实际配置与环境</summary>
                <pre
                    >{{ run.result.actual_config }}
{{ run.result.environment }}</pre
                >
            </details>
            <details>
                <summary>日志</summary>
                <pre>{{ run.result.log || '未提供日志' }}</pre>
            </details>
            <h3>模型产物</h3>
            <article v-for="a in run.result.artifacts" :key="a.id">
                <strong>{{ a.id }}</strong>
                <p>
                    {{ a.path }} · {{ a.availability }} · 身份范围
                    {{ a.identity_scope || '未声明' }}
                </p>
                <p>SHA-256 {{ a.sha256 }}</p>
                <p>远程登记未表示模型已下载或备份。</p>
            </article>
            <p v-if="!run.result.artifacts.length">未提供模型产物。</p>
            <h3>评测记录</h3>
            <article v-for="e in run.evaluations" :key="e.id">
                <strong>{{ e.task }}</strong>
                <p>
                    {{ e.dataset_version }} · {{ e.tool_version }} · 产物身份范围
                    {{ e.artifact_identity_scope }}
                </p>
                <pre>{{ e.metrics }}</pre>
            </article>
            <details>
                <summary>导入评测 JSON</summary>
                <native-text
                    v-model="evaluationText"
                    multiline
                    code
                    :rows="10"
                    :theme="theme"
                    label="评测 JSON"
                /><button @click="importEvaluation">导入评测</button>
            </details>
        </section>
        <section v-if="comparison">
            <h2>运行比较</h2>
            <p>{{ comparison.basis }}</p>
            <p>{{ comparison.missing }}</p>
            <p v-if="comparison.runs.length < 2">
                当前可比较运行少于两个；合成夹具默认排除，可显式勾选后比较。
            </p>
            <p v-else>条件差异：{{ comparison.differences.join('、') || '未发现声明条件差异' }}</p>
            <details>
                <summary>条件对照</summary>
                <pre>{{ comparison.conditions }}</pre>
            </details>
            <article v-for="r in comparison.runs" :key="r.id">
                <h3>
                    {{ r.synthetic ? '合成夹具 · ' : '' }}{{ r.plan_snapshot.name }} · {{ r.id }} ·
                    {{ r.status }}
                </h3>
                <metric-chart :rows="r.result.metrics" :theme="theme" />
            </article>
        </section>
    </main>
</template>
<script>
import axios from 'axios'
import { parseAdvancedPlan } from './planEditing.mjs'
import LegoStages from '@/components/manage/training/LegoStages.vue'
import MetricChart from '@/components/manage/training/MetricChart.vue'
import ParameterFields from '@/components/manage/training/ParameterFields.vue'
import { mapState } from 'pinia'
import { useTheme } from '@/stores/theme'
import NativeText from '@/components/manage/forms/NativeText.vue'
import NativeSelect from '@/components/manage/forms/NativeSelect.vue'
import { useUnsavedChanges, confirmDiscard } from '@/components/manage/forms/unsaved'
const empty = () => ({
    name: '新训练方案',
    model: '',
    tokenizer: '',
    model_revision: '',
    template: 'qwen',
    task: 'sft',
    modality: 'text',
    finetuning_type: 'lora',
    max_steps: 100,
    batch_size: 1,
    gradient_accumulation_steps: 8,
    learning_rate: 0.0001,
    seed: 42,
    data: [],
    group_id: null,
    strategy: { family: 'static', component: '', params: {} },
    advanced: {}
})
export default {
    name: 'ModelTraining',
    components: { NativeText, NativeSelect, ParameterFields, MetricChart, LegoStages },
    setup() {
        useUnsavedChanges(
            (vm) => !!vm.record && vm.hasPending,
            (vm) => {
                vm.record = null
            }
        )
    },
    data: () => ({
        backupId: '',
        host: null,
        hostForm: {
            alias: '',
            workdir: '/home/user/dataflex-runs',
            python: '/home/user/envs/dataflex/bin/python',
            gpus: '0'
        },
        hostProbe: null,
        controls: [],
        startKeys: {},
        runs: [],
        run: null,
        resultText: '',
        evaluationText: '',
        compareIds: [],
        includeSynthetic: false,
        comparison: null,
        bundles: [],
        components: [],
        compiled: null,
        parameterInvalid: false,
        descriptorText: JSON.stringify(
            {
                family: 'selection',
                name: 'my_selector',
                tasks: ['sft'],
                modalities: ['text'],
                requires_reference: false,
                fields: { seed: { type: 'integer', default: 42, minimum: 0 } },
                prerequisites: ['在 DataFlex 源码注册实现']
            },
            null,
            2
        ),
        families: [
            { value: 'static', label: '静态训练' },
            { value: 'selection', label: 'Selection · 选择' },
            { value: 'mixture', label: 'Mixture · 混合' },
            { value: 'reweighting', label: 'Reweighting · 加权' },
            { value: 'reorder', label: 'Reorder · 排序' },
            { value: 'lego', label: 'Lego · 组合' }
        ],
        plans: [],
        groups: [],
        releases: [],
        record: null,
        baseline: '',
        advancedText: '',
        advancedBaseline: '',
        advancedEdited: false,
        busy: false,
        error: '',
        notice: '',
        checks: null,
        groupName: '',
        groupShared: '{}',
        groupAllowed: 'strategy,seed',
        labels: {
            max_steps: '优化器步数',
            batch_size: '每设备 batch',
            gradient_accumulation_steps: '梯度累积步数',
            learning_rate: '学习率',
            seed: '随机种子'
        },
        roles: [
            { value: 'train', label: '训练域' },
            { value: 'validation', label: '验证集' },
            { value: 'reference', label: '策略目标参考集' }
        ],
        kinds: [
            { value: 'release', label: '平台发布版本' },
            { value: 'file', label: '本地文件' },
            { value: 'huggingface', label: 'Hugging Face' },
            { value: 'draft', label: '草稿（执行前需发布）' }
        ]
    }),
    computed: {
        ...mapState(useTheme, ['theme']),
        selectedComponent() {
            return this.components.find(
                (c) =>
                    c.family === this.record?.plan.strategy.family &&
                    c.name === this.record?.plan.strategy.component
            )
        },
        componentOptions() {
            return this.components
                .filter((c) => c.family === this.record?.plan.strategy.family)
                .map((c) => ({ value: c.name, label: c.name }))
        },
        hasPending() {
            return this.dirty || this.parameterInvalid || this.advancedEdited
        },
        dirty() {
            return !!this.record && JSON.stringify(this.record.plan) !== this.baseline
        },
        releaseOptions() {
            return this.releases.map((r) => ({
                value: r.id,
                label: `${r.name || r.draft_id} · v${r.version} · ${r.row_count ?? r.sample_ids?.length ?? ''} 样本`
            }))
        }
    },
    mounted() {
        this.load()
        this.startPolling()
    },
    activated() {
        this.startPolling()
    },
    deactivated() {
        clearInterval(this.pollTimer)
        this.pollTimer = null
    },
    beforeUnmount() {
        clearInterval(this.pollTimer)
    },
    methods: {
        startPolling() {
            if (!this.pollTimer) this.pollTimer = setInterval(() => this.pollControls(), 5000)
        },
        async pollControls() {
            if (this.busy || this.polling || !this.host) return
            const active = this.controls.filter(
                (c) => !['completed', 'failed', 'stopped'].includes(c.phase)
            )
            if (!active.length) return
            this.polling = true
            try {
                for (const c of active) await this.request('post', '/controls/' + c.id + '/sync')
                this.controls = await this.request('get', '/controls')
                this.runs = await this.request('get', '/runs')
                if (this.run && active.some((c) => c.id === this.run.id))
                    this.run = await this.request('get', '/runs/' + this.run.id)
            } catch (e) {
                this.error = '同步未完成：' + (e.response?.data?.message || e.message)
            } finally {
                this.polling = false
            }
        },
        setFamily(f) {
            const old = this.record.plan.strategy
            this.strategyCache ||= {}
            this.strategyCache[old.family] = JSON.parse(JSON.stringify(old))
            this.record.plan.strategy = this.strategyCache[f] || {
                family: f,
                component: '',
                params: {},
                update_step: 10,
                update_times: 1,
                warmup_step: 0
            }
            this.compiled = null
        },
        setComponent(name) {
            const c = this.components.find(
                (c) => c.family === this.record.plan.strategy.family && c.name === name
            )
            this.record.plan.strategy.component = name
            this.record.plan.strategy.params = JSON.parse(JSON.stringify(c?.defaults || {}))
            this.compiled = null
            this.parameterInvalid = false
        },
        uploadBundle(event) {
            const file = event.target.files[0]
            if (!file) return
            return this.action(async () => {
                const data = new FormData()
                data.append('file', file)
                const b = await this.request('post', '/bundles/import', data)
                this.bundles = await this.request('get', '/bundles')
                this.notice = '运行包已核验导入，尚未执行'
                event.target.value = ''
            })
        },
        backupTraining() {
            return this.action(async () => {
                this.backupId = (await this.request('post', '/backups')).id
                this.notice = '本地备份已生成并核验，远端 checkpoint 未包含'
            })
        },
        saveHost() {
            return this.action(async () => {
                this.host = await this.request('put', '/host', this.hostForm)
                this.notice = '固定主机已保存，尚未建立连接'
            })
        },
        probeHost() {
            return this.action(async () => {
                this.hostProbe = await this.request('post', '/host/probe')
            })
        },
        startBundle(b) {
            return this.action(async () => {
                this.startKeys[b.id] ||= crypto.randomUUID()
                await this.request('post', '/start', {
                    bundle_id: b.id,
                    idempotency_key: this.startKeys[b.id]
                })
                this.controls = await this.request('get', '/controls')
                this.notice = '已提交主机控制请求，请同步查看确认状态'
            })
        },
        control(c, action) {
            return this.action(async () => {
                await this.request('post', '/controls/' + c.id + '/' + action)
                this.controls = await this.request('get', '/controls')
                this.runs = await this.request('get', '/runs')
                if (this.run?.id === c.id) this.run = await this.request('get', '/runs/' + c.id)
            })
        },
        rerun(c) {
            this.startKeys[c.bundle_id] = crypto.randomUUID()
            return this.startBundle({ id: c.bundle_id })
        },
        openRun(id) {
            return this.action(async () => {
                this.run = await this.request('get', '/runs/' + id)
                this.evaluationText = JSON.stringify(
                    {
                        attempt_id: id,
                        artifact_id: '',
                        artifact_sha256: '',
                        task: '',
                        dataset_version: '',
                        metric_definitions: {},
                        metrics: {},
                        tool_version: '',
                        config: {}
                    },
                    null,
                    2
                )
            })
        },
        importResult() {
            return this.action(async () => {
                const r = await this.request('post', '/results/import', JSON.parse(this.resultText))
                this.runs = await this.request('get', '/runs')
                this.run = await this.request('get', '/runs/' + r.id)
                this.notice = r.idempotent ? '结果已存在，未重复导入' : '结果已导入'
            })
        },
        importEvaluation() {
            return this.action(async () => {
                await this.request('post', '/evaluations', JSON.parse(this.evaluationText))
                this.run = await this.request('get', '/runs/' + this.run.id)
                this.notice = '评测已绑定对应产物'
            })
        },
        compareRuns() {
            return this.action(async () => {
                this.comparison = await this.request('post', '/compare', {
                    attempts: this.compareIds,
                    include_synthetic: this.includeSynthetic
                })
            })
        },
        makeBundle() {
            return this.action(async () => {
                const b = await this.request('post', '/plans/' + this.record.id + '/bundles')
                this.bundles.unshift(b)
                this.notice = '运行包已生成，尚未执行训练'
            })
        },
        compile() {
            return this.action(async () => {
                this.compiled = await this.request('post', '/plans/' + this.record.id + '/compile')
                this.checks = this.compiled.checks
            })
        },
        addDescriptor() {
            return this.action(async () => {
                await this.request('post', '/components', JSON.parse(this.descriptorText))
                this.components = (await this.request('get', '/catalog')).components
                this.notice = '组件描述已保存，运行环境与实现待验证'
            })
        },
        async request(method, path, data) {
            const r = await axios({ method, url: '/api/v1/training' + path, data })
            if (!r.data.success) throw Error(r.data.message)
            return r.data.data
        },
        async action(fn) {
            if (this.busy) return
            this.busy = true
            this.error = ''
            this.notice = ''
            try {
                await fn()
            } catch (e) {
                this.error =
                    typeof e.response?.data?.detail === 'string'
                        ? e.response.data.detail
                        : JSON.stringify(
                              e.response?.data?.detail || e.response?.data?.message || e.message
                          )
            } finally {
                this.busy = false
            }
        },
        load() {
            return this.action(async () => {
                let catalog
                ;[
                    this.plans,
                    this.groups,
                    this.releases,
                    catalog,
                    this.bundles,
                    this.runs,
                    this.host,
                    this.controls
                ] = await Promise.all(
                    [
                        '/plans',
                        '/groups',
                        '/releases',
                        '/catalog',
                        '/bundles',
                        '/runs',
                        '/host',
                        '/controls'
                    ].map((p) => this.request('get', p))
                )
                this.components = catalog.components
                if (this.host) this.hostForm = { ...this.host.config }
            })
        },
        setRecord(r) {
            this.record = r
            this.baseline = JSON.stringify(r.plan)
            this.advancedBaseline = JSON.stringify(r.plan, null, 2)
            this.advancedText = this.advancedBaseline
            this.advancedEdited = false
            this.checks = null
            this.compiled = null
            this.parameterInvalid = false
            this.strategyCache = {}
        },
        async newPlan() {
            if (this.hasPending && !(await confirmDiscard(this))) return
            this.setRecord({ plan: empty() })
        },
        async close() {
            if (this.hasPending && !(await confirmDiscard(this))) return
            this.record = null
            this.load()
        },
        open(id) {
            return this.action(async () => {
                this.setRecord(await this.request('get', '/plans/' + id))
            })
        },
        save() {
            if (this.advancedEdited) {
                this.error = '高级 JSON 尚未应用，请先应用到表单或从表单更新'
                return
            }
            return this.action(async () => {
                const r = this.record
                this.setRecord(
                    await this.request(r.id ? 'put' : 'post', '/plans' + (r.id ? '/' + r.id : ''), {
                        plan: r.plan,
                        expected_version: r.version
                    })
                )
                this.plans = await this.request('get', '/plans')
                this.notice = '方案已保存'
            })
        },
        async copy() {
            if (this.hasPending && !(await confirmDiscard(this))) return
            return this.action(async () => {
                this.setRecord(await this.request('post', '/plans/' + this.record.id + '/copy'))
                this.plans = await this.request('get', '/plans')
                this.notice = '副本已创建'
            })
        },
        check() {
            return this.action(async () => {
                this.checks = await this.request('post', '/plans/' + this.record.id + '/check')
            })
        },
        addBinding() {
            this.record.plan.data.push({
                role: 'train',
                kind: 'release',
                ref: '',
                domain: 'default',
                revision: '',
                subset: '',
                split: 'train',
                sha256: '',
                columns: { prompt: 'instruction', query: 'input', response: 'output' }
            })
        },
        addGroup() {
            return this.action(async () => {
                const g = await this.request('post', '/groups', {
                    name: this.groupName,
                    shared_conditions: JSON.parse(this.groupShared),
                    allowed_differences: this.groupAllowed
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean)
                })
                this.groups.unshift(g)
                this.record.plan.group_id = g.id
                this.groupName = ''
            })
        },
        editAdvanced(value) {
            this.advancedText = value
            this.advancedEdited = value !== this.advancedBaseline
        },
        syncAdvanced() {
            this.advancedBaseline = JSON.stringify(this.record.plan, null, 2)
            this.advancedText = this.advancedBaseline
            this.advancedEdited = false
        },
        applyAdvanced() {
            try {
                this.record.plan = parseAdvancedPlan(this.advancedText, empty())
                this.advancedBaseline = this.advancedText
                this.advancedEdited = false
                this.error = ''
            } catch (e) {
                this.error = e.message
            }
        }
    }
}
</script>
<style scoped>
.training {
    flex: 1;
    min-width: 0;
    height: 100%;
    overflow: auto;
    box-sizing: border-box;
    padding: 28px;
    color: #25334c;
    background: #f7f8fb;
    font-size: 14px;
    overflow-wrap: anywhere;
}
header,
.actions,
nav {
    display: flex;
    gap: 12px;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
}
h1 {
    margin: 0;
}
h2 {
    font-size: 19px;
}
p {
    line-height: 1.7;
}
section,
details {
    background: #fff;
    border: 1px solid #e2e7f0;
    border-radius: 10px;
    padding: 22px;
    margin: 18px 0;
}
.grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px 22px;
}
label {
    display: block;
    line-height: 2;
    margin: 8px 0;
}
input,
button {
    font: inherit;
    color: inherit;
    background: transparent;
    border: 1px solid #d9dfeb;
    border-radius: 6px;
    padding: 9px;
    box-sizing: border-box;
}
input {
    width: 100%;
    height: 38px;
}
input[type='checkbox'] {
    width: auto;
    height: auto;
    margin-right: 10px;
}
button {
    cursor: pointer;
}
button:disabled {
    opacity: 0.45;
    cursor: default;
}
.primary {
    background: #4e5bd5;
    color: white;
}
article {
    border-bottom: 1px solid #e2e7f0;
    padding: 10px 0 20px;
}
.row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    width: 100%;
    text-align: left;
    margin: 8px 0;
    padding: 16px;
}
.error {
    color: #ae342b;
    background: #fff0ed;
    padding: 12px;
}
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
}
td,
th {
    text-align: left;
    border-bottom: 1px solid #c5cbd8;
    padding: 8px;
    overflow-wrap: anywhere;
}
details {
    overflow: auto;
}
a {
    color: #4e5bd5;
}
pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}
.dark {
    background: #20242d;
    color: #dfe5ef;
}
.dark section,
.dark details,
.dark input,
.dark button {
    background: #292e39;
    border-color: #424b5b;
}
.dark .primary {
    background: #4e5bd5;
}
.dark .error {
    background: #502d30;
    color: #ffd2d2;
}
@media (max-width: 800px) {
    .training {
        padding: 52px 16px 16px;
    }
    .grid {
        grid-template-columns: 1fr;
    }
    .row {
        flex-direction: column;
    }
}
</style>
