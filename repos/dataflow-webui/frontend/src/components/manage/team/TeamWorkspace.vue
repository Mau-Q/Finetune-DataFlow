<template>
    <section class="workspace">
        <header>
            <div>
                <small>{{ project?.name || '系统管理' }}</small>
                <h1>{{ titles[tab] }}</h1>
                <p>{{ subtitles[tab] }}</p>
            </div>
            <button :disabled="busy" @click="refresh">刷新</button>
        </header>
        <nav class="tabs">
            <button
                v-for="t in tabs"
                :key="t"
                :class="{ selected: tab === t }"
                @click="changeTab(t)"
            >
                {{ titles[t] }}
            </button>
        </nav>
        <p v-if="error" role="alert" class="team-error feedback">{{ error }}</p>
        <p v-if="notice" role="status" class="feedback">{{ notice }}</p>
        <template v-if="tab === 'sources'">
            <div class="tools">
                <label
                    >生成情况<select v-model="filter" @change="writeWorkspaceState('source-filter', filter); offset = 0; loadSources()">
                        <option value="">全部来源</option>
                        <option v-for="(name, k) in filters" :key="k" :value="k">{{ name }}</option>
                    </select></label
                ><span>{{ sources.total }} 个来源</span>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>原始数据集</th>
                            <th>生成情况</th>
                            <th>内容身份</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        <template v-for="s in sources.items" :key="s.id"
                            ><tr>
                                <td>
                                    <strong>{{ s.name }}</strong>
                                </td>
                                <td>
                                    <span v-if="s.datasets.length" class="badge good"
                                        >已生成 {{ s.datasets.length }} 个数据集</span
                                    ><span v-if="s.active.length" class="badge"
                                        >生成中 {{ s.active.length }} 个任务</span
                                    ><span v-if="s.pending.length" class="badge warn"
                                        >待收集 {{ s.pending.length }} 个任务</span
                                    ><span v-if="s.releases.length" class="badge good"
                                        >已发布 {{ s.releases.length }} 个版本</span
                                    ><span
                                        v-if="!s.generated && !s.active.length && !s.pending.length"
                                        >未生成</span
                                    ><small v-if="s.zero_samples.length">已完成，无有效样本</small>
                                </td>
                                <td>
                                    <span v-if="s.old_content.length" class="badge warn"
                                        >结果基于旧内容</span
                                    ><small v-if="s.unknown_source.length">来源待确认</small>
                                </td>
                                <td>
                                    <button @click="expanded = expanded === s.id ? '' : s.id">
                                        关联详情
                                    </button>
                                </td>
                            </tr>
                            <tr v-if="expanded === s.id">
                                <td colspan="4" class="detail">
                                    <p>输入覆盖率：未知。产物条数不代表输入覆盖率。</p>
                                    <p v-for="d in s.datasets" :key="d.id">
                                        <a :href="draftUrl(d.id)">{{ d.name }}</a> · 本来源
                                        {{ d.source_sample_count }} 条 / 集合
                                        {{ d.total_sample_count }} 条
                                        {{ d.archived ? '（已归档）' : '' }}
                                    </p>
                                    <p v-for="t in s.tasks" :key="t.task_id">
                                        任务 {{ t.task_id }} · {{ t.status }} ·
                                        {{ t.input_identity ? '输入已固定' : '来源待确认' }}
                                    </p>
                                    <p v-for="r in s.releases" :key="r.id">
                                        发布 {{ r.id }} · 本来源 {{ r.source_sample_count }} 条
                                    </p>
                                </td>
                            </tr></template
                        >
                    </tbody>
                </table>
            </div>
            <div class="pager">
                <button
                    :disabled="offset === 0"
                    @click="
                        offset = Math.max(0, offset - 30);
                        loadSources()
                    "
                >
                    上一页</button
                ><span
                    >{{ offset + 1 }}–{{ Math.min(offset + 30, sources.total) }} /
                    {{ sources.total }}</span
                ><button
                    :disabled="offset + 30 >= sources.total"
                    @click="
                        offset += 30;
                        loadSources()
                    "
                >
                    下一页
                </button>
            </div>
        </template>
        <template v-if="tab === 'reviews'">
            <details v-if="canDevelop" class="card" :open="!!selection?.source">
                <summary>发起人工评测</summary>
                <form class="grid" @submit.prevent="createReview">
                    <label
                        >数据集或版本<select v-model="reviewForm.source" required>
                            <option value="">请选择</option>
                            <option v-for="c in choices" :key="c.id" :value="c.id">
                                {{ c.label }}
                            </option>
                        </select></label
                    ><label
                        >抽样数量<input
                            v-model.number="reviewForm.count"
                            type="number"
                            min="1"
                            placeholder="留空为全量" /></label
                    ><label>随机种子<input v-model="reviewForm.seed" /></label
                    ><label>批次名称<input v-model="reviewForm.name" placeholder="可选" /></label
                    ><label class="wide">允许评测人员
<select v-model="selectedReviewers" multiple required aria-label="允许评测人员"><option v-for="r in eligibleReviewers" :key="r.id" :value="r.id">{{ r.name }}</option></select>
<small>每条样本只需一人评测。可选择多位成员领取不同样本。</small></label>
                    <details class="wide">
                        <summary>评分模板</summary>
                        <textarea v-model="templateJson" rows="7" />
                    </details>
                    <div class="wide">
                        <button class="primary" :disabled="busy">创建固定批次</button>
                    </div>
                </form>
            </details>
            <div v-if="!batch" class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>批次</th>
                            <th>进度</th>
                            <th>范围</th>
                            <th>状态</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr v-for="b in batches" :key="b.id">
                            <td>
                                <strong>{{ b.name }}</strong
                                ><small>{{ date(b.created_at) }}</small>
                            </td>
                            <td>
                                {{ b.summary.submitted }} / {{ b.summary.total }} 已提交 ·
                                {{ b.summary.pass }} 通过
                            </td>
                            <td>
                                {{ b.sampled ? '抽样' : '全量' }} {{ b.count }} /
                                {{ b.total_available }}
                            </td>
                            <td>{{ state(b.status) }}</td>
                            <td><button @click="openBatch(b.id)">进入评测</button></td>
                        </tr>
                    </tbody>
                </table>
                <p v-if="!batches.length" class="empty">
                    暂无人工评测批次。{{
                        canDevelop ? '可在上方发起评测。' : '分配给你的批次会显示在这里。'
                    }}
                </p>
            </div>
            <template v-else
                ><div class="tools">
                    <button @click="leaveBatch">← 批次列表</button><strong>{{ batch.name }}</strong
                    ><span>{{ batch.sampled ? '结论仅覆盖抽中样本' : '全量批次' }}</span
                    ><button v-if="canDevelop" @click="derive">整理通过样本</button
                    ><button v-if="canDevelop && batch.status !== 'closed'" @click="closeBatch">
                        关闭批次
                    </button>
                </div>
                <div class="metrics">
                    <div
                        v-for="(label, key) in {
                            total: '批次样本',
                            submitted: '已提交',
                            pass: '通过',
                            needs_changes: '需修改',
                            reject: '拒绝'
                        }"
                        :key="key"
                    >
                        <b>{{ batch.summary[key] }}</b
                        ><span>{{ label }}</span>
                    </div>
                    <div>
                        <b>{{
                            batch.summary.pass_rate === null
                                ? '暂无'
                                : Math.round(batch.summary.pass_rate * 100) + '%'
                        }}</b
                        ><span>通过 / 已提交</span>
                    </div>
                </div>
                <div v-if="item" class="workbench">
                    <aside>
                        <button
                            v-for="(i, n) in batch.items"
                            :key="i.id"
                            :class="{ selected: n === index }"
                            @click="selectItem(n)"
                        >
                            样本 {{ n + 1 }}<small>{{ itemState(i) }}</small>
                        </button>
                    </aside>
                    <div class="review-body">
                        <div class="tools">
                            <strong>样本 {{ index + 1 }} / {{ batch.items.length }}</strong
                            ><span class="badge">{{ itemState(item) }}</span
                            ><button
                                v-if="
                                    canReview &&
                                    item.status === 'pending' &&
                                    batch.status === 'in_progress'
                                "
                                @click="actItem('claim')"
                            >
                                领取此条</button
                            ><button
                                v-if="owned"
                                @click="actItem('release', { reason: '本人释放' })"
                            >
                                释放</button
                            ><button
                                v-if="canDevelop && item.status === 'submitted'"
                                @click="reopen"
                            >
                                重开
                            </button>
                        </div>
                        <div class="columns">
                            <section class="card">
                                <h3>来源与上下文</h3>
                                <p v-if="item.source_missing" class="warn feedback">
                                    来源缺失或待确认，可记录无法判断及原因。
                                </p>
                                <p v-for="s in item.sources" :key="s.task_id + s.artifact_id">
                                    任务 {{ s.task_id }} · 产物 {{ s.artifact_id }} · 第
                                    {{ Number(s.row_index) + 1 }} 条
                                </p>
                                <img
                                    v-for="mid in media"
                                    :key="mid"
                                    :src="`/api/v1/team-data/reviews/${batch.id}/items/${item.id}/media/${mid}`"
                                    alt="样本引用图片"
                                />
                                <p v-for="c in item.context || []" :key="c.id">
                                    <a
                                        :href="`/api/v1/team-data/reviews/${batch.id}/items/${item.id}/context/${c.id}`"
                                        target="_blank"
                                        rel="noopener"
                                        >查看 {{ c.name }}</a
                                    >
                                </p><iframe v-for="c in item.context || []" :key="'frame-'+c.id" :src="`/api/v1/team-data/reviews/${batch.id}/items/${item.id}/context/${c.id}`" :title="c.name" sandbox="allow-same-origin" class="context-frame"></iframe>
                                <small>修订 {{ item.revision.slice(0, 16) }}</small>
                            </section>
                            <section class="card">
                                <h3>生成内容</h3>
                                <template v-if="item.row.messages"
                                    ><article v-for="(m, n) in item.row.messages" :key="n">
                                        <strong>{{ m.role }}</strong>
                                        <p class="preserve">{{ m.content }}</p>
                                    </article></template
                                >
                                <div v-else v-for="(v, k) in item.row" :key="k" class="field">
                                    <small>{{ fieldLabel(k) }}</small>
                                    <p class="preserve">
                                        {{ typeof v === 'string' ? v : JSON.stringify(v, null, 2) }}
                                    </p>
                                </div>
                            </section>
                        </div>
                        <form class="card" @submit.prevent="submit">
                            <fieldset :disabled="!owned || busy">
                                <legend>人工评测</legend>
                                <div
                                    v-for="d in batch.template.dimensions"
                                    :key="d.id"
                                    class="score"
                                >
                                    <label
                                        >{{ d.name }}<small>{{ d.description }}</small></label
                                    ><select v-model="scores[d.id]" :aria-label="d.name">
                                        <option value="">请选择</option>
                                        <option v-for="n in 5" :key="n" :value="n">
                                            {{ n }} 分
                                        </option>
                                        <option value="unknown">无法判断</option></select
                                    ><input
                                        v-if="scores[d.id] === 'unknown'"
                                        v-model="unknown[d.id]"
                                        placeholder="无法判断的原因"
                                    />
                                </div>
                                <div class="grid">
                                    <label
                                        >最终结论<select v-model="conclusion" required>
                                            <option value="">请选择</option>
                                            <option value="pass">通过</option>
                                            <option value="needs_changes">需修改</option>
                                            <option value="reject">拒绝</option>
                                        </select></label
                                    ><label
                                        >问题标签<select v-model="tags" multiple>
                                            <option v-for="t in batch.template.tags" :key="t">
                                                {{ t }}
                                            </option>
                                        </select></label
                                    ><label class="wide"
                                        >评语<textarea v-model="comment" rows="3" />
                                    </label>
                                </div>
                                <details>
                                    <summary>修改并通过</summary>
                                    <label>修订内容<textarea v-model="revised" rows="8" /></label
                                    ><label>修改原因<input v-model="reason" /></label
                                    ><button type="button" @click="revise">保存修订并通过</button>
                                    <p>原发布版本始终保留；草稿并发修改时整笔失败。</p>
                                </details>
                                <div class="tools">
                                    <button type="button" @click="save(false)">保存进度</button
                                    ><button type="button" @click="save(true)">
                                        跳过，稍后继续</button
                                    ><button class="primary">提交评测</button
                                    ><small v-if="dirty">有未保存内容</small>
                                </div>
                            </fieldset>
                            <p v-if="item.decision" class="feedback">
                                {{ result(item.decision.conclusion) }} ·
                                {{ item.decision.reviewer }} · {{ date(item.decision.time)
                                }}<br />{{ item.decision.comment }}
                            </p>
                            <details v-if="item.history.length">
                                <summary>历史记录</summary>
                                <pre>{{ item.history }}</pre>
                            </details>
                        </form>
                        <div class="pager">
                            <button :disabled="index === 0" @click="selectItem(index - 1)">
                                上一条</button
                            ><button
                                :disabled="index + 1 >= batch.items.length"
                                @click="selectItem(index + 1)"
                            >
                                下一条
                            </button>
                        </div>
                    </div>
                </div></template
            >
        </template>
        <template v-if="tab === 'exports'"
            ><section class="card">
                <h2>创建导出快照</h2>
                <form class="grid" @submit.prevent="createExport">
                    <label
                        >来源<select v-model="exportForm.source">
                            <option value="">请选择</option>
                            <option v-for="c in choices" :key="c.id" :value="c.id">
                                {{ c.label }}
                            </option>
                        </select></label
                    ><label
                        >样本范围<select v-model="exportForm.batch">
                            <option value="">全部样本</option>
                            <option v-for="b in batches" :key="b.id" :value="b.id">
                                仅此批次通过 · {{ b.name }}
                            </option>
                        </select></label
                    ><label
                        >格式<select v-model="exportForm.format">
                            <option v-for="(name, k) in formats" :key="k" :value="k">
                                {{ name }}
                            </option>
                        </select></label
                    ><label v-if="exportForm.format === 'package'"
                        >包内格式<select v-model="exportForm.data_format">
                            <option
                                v-for="k in ['jsonl', 'alpaca', 'messages', 'dpo']"
                                :key="k"
                                :value="k"
                            >
                                {{ formats[k] }}
                            </option>
                        </select></label
                    >
                    <details class="wide">
                        <summary>字段映射</summary>
                        <p>键为目标字段，值为已有源字段；input 可留空。</p>
                        <textarea v-model="mapping" rows="3" />
                    </details>
                    <label v-if="exportForm.format !== 'package'" class="wide check"
                        ><input type="checkbox" v-model="referencesOnly" />确认仅 JSONL
                        不包含媒体，只保留相对引用。</label
                    >
                    <div class="wide tools">
                        <button type="button" @click="previewExport">检查兼容性</button
                        ><button class="primary" :disabled="!preview || busy">确认创建快照</button>
                    </div>
                </form>
                <div v-if="preview" class="feedback">
                    <p>
                        兼容 {{ preview.compatible }} / {{ preview.total }} 条 ·
                        {{ preview.media_included ? '包含媒体' : '不包含媒体' }}
                    </p>
                    <p>
                        输出：{{ preview.output_fields?.join('、') }} · 排除：{{
                            preview.excluded_fields?.join('、') || '无'
                        }}
                    </p>
                    <p v-for="e in preview.errors" :key="e.sample_id" class="team-error">
                        {{ e.sample_id }}：{{ e.error }}
                    </p>
                </div>
            </section>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>创建时间</th>
                            <th>来源 / 格式</th>
                            <th>样本数</th>
                            <th>状态</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        <template v-for="e in exports" :key="e.id"
                            ><tr>
                                <td>{{ date(e.created_at) }}</td>
                                <td>
                                    {{ e.kind === 'release' ? '发布版本' : '草稿快照' }} ·
                                    {{ e.format }}
                                </td>
                                <td>{{ e.row_count }}</td>
                                <td>
                                    {{ state(e.status)
                                    }}<small class="team-error">{{ e.error }}</small>
                                </td>
                                <td>
                                    <a
                                        v-if="e.status === 'ready'"
                                        :href="`/api/v1/team-data/exports/${e.id}/download`"
                                        download
                                        >下载</a
                                    ><button @click="expanded = expanded === e.id ? '' : e.id">
                                        清单
                                    </button><button v-if="e.status==='ready'" @click="expireExport(e.id)">清理临时文件</button>
                                </td>
                            </tr>
                            <tr v-if="expanded === e.id">
                                <td colspan="5">
                                    <pre>{{ JSON.stringify(e, null, 2) }}</pre>
                                </td>
                            </tr></template
                        >
                    </tbody>
                </table>
                <p v-if="!exports.length" class="empty">
                    暂无导出。创建快照不会发布版本或启动训练。
                </p>
            </div></template
        >
        <template v-if="tab === 'admin'"
            ><div class="grid">
                <section v-if="user.admin" class="card">
                    <h2>账号与邀请</h2>
                    <form @submit.prevent="invite">
                        <label>账号名称<input v-model="accountName" required /></label
                        ><button>生成一次性邀请</button>
                    </form>
                    <p v-if="inviteToken" class="feedback">
                        一次性邀请码（1 小时有效，请手动交付）：<code>{{ inviteToken }}</code>
                    </p>
                    <table>
                        <tbody>
                            <tr v-for="u in users" :key="u.id">
                                <td>
                                    {{ u.name }}<small>{{ u.id }}</small>
                                </td>
                                <td>{{ u.enabled ? '可用' : '禁用' }}</td>
                                <td>
                                    <button @click="toggleUser(u)">
                                        {{ u.enabled ? '禁用' : '启用' }}</button
                                    ><button @click="resetUser(u)">重置</button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </section>
                <section v-if="user.admin" class="card">
                    <h2>新建项目</h2>
                    <form @submit.prevent="newProject">
                        <label>项目名称<input v-model="projectName" required /></label
                        ><button>创建项目</button>
                    </form>
                <details><summary>系统管理范围内的项目</summary><p class="muted">跨项目管理需要显式进入，并记录审计。</p><p v-for="p in allProjects" :key="p.id">{{ p.name }} <button @click="adminEnter(p.id)">以管理员身份进入</button></p></details></section>
                <section v-if="project && roles.includes('manage')" class="card">
                    <h2>项目成员</h2>
                    <table>
                        <tbody>
                            <tr v-for="m in members" :key="m.user">
                                <td>
                                    {{ m.name }}<small>{{ m.user }}</small>
                                </td>
                                <td>{{ m.roles.join(' · ') }}</td>
                                <td>
                                    <button
                                        @click="
                                            memberForm = {
                                                user: m.user,
                                                roles: [...m.roles],
                                                version: m.version
                                            }
                                        "
                                    >
                                        编辑
                                    </button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                    <form @submit.prevent="saveMember">
                        <label>账号 ID<input v-model="memberForm.user" required /></label
                        ><label
                            >权限<select v-model="memberForm.roles" multiple>
                                <option value="manage">项目管理</option>
                                <option value="develop">项目开发</option>
                                <option value="review">项目评测</option>
                            </select></label
                        ><button>保存权限</button>
                    </form>
                </section>
                <section class="card">
                    <h2>修改我的密码</h2>
                    <form @submit.prevent="changePassword">
                        <label
                            >当前密码<input
                                v-model="currentPassword"
                                type="password"
                                autocomplete="current-password"
                                required /></label
                        ><label
                            >新密码<input
                                v-model="newPassword"
                                type="password"
                                autocomplete="new-password"
                                minlength="12"
                                required /></label
                        ><button>保存并重新登录</button>
                    </form>
                </section>
            </div>
            <details v-if="audit.length" class="card">
                <summary>关键操作记录</summary>
                <table>
                    <tbody>
                        <tr v-for="a in audit" :key="a.id">
                            <td>{{ date(a.time * 1000) }}</td>
                            <td>{{ a.actor }}</td>
                            <td>{{ a.action }}</td>
                            <td>{{ a.object }}</td>
                            <td>{{ a.result }}</td>
                        </tr>
                    </tbody>
                </table>
            </details></template
        >
    </section>
</template>
<script setup>
import {readWorkspaceState,writeWorkspaceState} from '@/hooks/dataflow/workspaceState'
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { request } from './client'
const props = defineProps(['user', 'project', 'selection']),
    emit = defineEmits(['refresh'])
const roles = computed(() => props.project?.roles || []),
    canDevelop = computed(() => roles.value.some((r) => ['manage', 'develop'].includes(r))),
    canReview = computed(() => roles.value.includes('review'))
const titles = {
        sources: '来源与生成情况',
        reviews: '人工评测',
        exports: '数据导出',
        admin: '团队设置'
    },
    subtitles = {
        sources: '从原始输入追溯生成任务、样本和发布成果。',
        reviews: '对照来源检查固定样本，保存评分、评语与修订。',
        exports: '选择草稿或发布版本，检查格式并下载固定内容。',
        admin: '管理账号、项目和成员权限。'
    },
    formats = {
        jsonl: '原始 JSONL',
        alpaca: 'Alpaca',
        messages: '对话 JSONL',
        dpo: 'DPO JSONL',
        package: '数据与媒体 ZIP（图文推荐）',
        review_csv: '评测明细 CSV',
        review_jsonl: '评测明细 JSONL'
    },
    filters = {
        generated: '有生成成果',
        active: '有活动任务',
        pending: '有待收集结果',
        published: '有发布版本',
        unknown_source: '来源待确认'
    }
const tabs = computed(() => [
    ...(canDevelop.value ? ['sources'] : []),
    'reviews',
    ...(canDevelop.value ? ['exports'] : []),
    'admin'
])
const tab = ref(canDevelop.value ? 'sources' : 'reviews'),
    busy = ref(false),
    error = ref(''),
    notice = ref(''),
    expanded = ref(''),
    filter = ref(readWorkspaceState('source-filter', 'generated')),
    offset = ref(readWorkspaceState('source-offset', 0)),
    sources = ref({ items: [], total: 0 }),
    drafts = ref([]),
    releases = ref([]),
    batches = ref([]),
    exports = ref([]),
    batch = ref(null),
    index = ref(0),
    scores = ref({}),
    unknown = ref({}),
    conclusion = ref(''),
    comment = ref(''),
    tags = ref([]),
    revised = ref(''),
    reason = ref(''),
    baseline = ref(''),
    users = ref([]),
    members = ref([]),
    audit = ref([]),
    accountName = ref(''),
    projectName = ref(''),
    inviteToken = ref(''),
    currentPassword = ref(''),
    newPassword = ref(''),
    memberForm = ref({ user: '', roles: [], version: 0 })
const allProjects=ref([])
const eligibleReviewers=ref([]), selectedReviewers=ref([props.user.id])
const templateJson = ref(
        JSON.stringify(
            {
                dimensions: [
                    { id: 'correctness', name: '正确性', required: true },
                    { id: 'support', name: '来源支持', required: true },
                    { id: 'usability', name: '表达与可用性', required: true }
                ],
                tags: ['事实错误', '缺少依据', '答非所问', '格式错误', '重复', '图片不匹配', '其他']
            },
            null,
            2
        )
    ),
    reviewForm = ref({ source: '', count: null, seed: '0', name: '' }),
    exportForm = ref({ source: '', batch: '', format: 'package', data_format: 'jsonl' }),
    mapping = ref('{}'),
    referencesOnly = ref(false),
    preview = ref(null)
const choices = computed(() => [
        ...drafts.value.map((d) => ({ id: d.id, label: d.name + ' · 当前草稿', kind: 'draft' })),
        ...releases.value.map((r) => ({
            id: r.id,
            label: r.name + ' · v' + r.version,
            kind: 'release'
        }))
    ]),
    item = computed(() => batch.value?.items[index.value]),
    owned = computed(
        () =>
            item.value?.owner === props.user.id &&
            item.value?.status === 'claimed' &&
            batch.value.status === 'in_progress'
    )
const media = computed(() => {
    const row = item.value?.row || {},
        refs = [...(row.images || []), ...(row.image ? [row.image] : [])]
    for (const m of row.messages || [])
        if (Array.isArray(m.content))
            for (const b of m.content)
                if (b.type === 'image_url')
                    refs.push(typeof b.image_url === 'object' ? b.image_url.url : b.image_url)
    return [...new Set(refs.map((r) => batch.value.media_bindings[r]).filter(Boolean))]
})
const formState = () =>
        JSON.stringify([
            scores.value,
            unknown.value,
            conclusion.value,
            comment.value,
            tags.value,
            revised.value,
            reason.value
        ]),
    dirty = computed(() => owned.value && baseline.value !== formState()),
    uuid = () => crypto.randomUUID(),
    date = (x) => new Date(x).toLocaleString(),
    state = (x) =>
        ({
            in_progress: '进行中',
            completed: '已完成',
            closed: '已关闭',
            ready: '可下载',
            preparing: '准备中',
            failed: '失败',
            expired: '已过期',
            cancelled: '已取消'
        })[x] || x,
    result = (x) => ({ pass: '通过', needs_changes: '需修改', reject: '拒绝' })[x] || x,
    fieldLabel = (k) =>
        ({
            instruction: '指令',
            input: '输入',
            output: '回答',
            prompt: '问题',
            chosen: '优选回答',
            rejected: '较差回答'
        })[k] || k,
    itemState = (i) =>
        i.status === 'submitted'
            ? result(i.decision?.conclusion)
            : i.status === 'claimed'
              ? i.owner === props.user.id
                  ? '我已领取'
                  : '已被领取'
              : i.skipped
                ? '稍后处理'
                : '待领取',
    draftUrl = (id) => `/#/m/training-datasets?dataset=${encodeURIComponent(id)}`
async function action(fn) {
    if (busy.value) return
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
        await fn()
    } catch (e) {
        error.value = e.message
    } finally {
        busy.value = false
    }
}
function discard() {
    return !dirty.value || window.confirm('有未保存的评测内容，是否放弃并离开？')
}
async function changeTab(t) {
    if (!discard()) return
    tab.value = t
    batch.value = null
    await refresh()
}
async function loadSources() {
    writeWorkspaceState('source-offset', offset.value)
    sources.value = await request(
        `/api/v1/team-data/sources?offset=${offset.value}&limit=30${filter.value ? '&' + filter.value + '=true' : ''}${props.selection?.tab==='sources'&&props.selection.source?'&source='+encodeURIComponent(props.selection.source):''}`
    )
}
async function loadChoices() {
    eligibleReviewers.value=await request(`/team/projects/${props.project.id}/reviewers`)
    drafts.value = await request('/api/v1/library/drafts')
    releases.value = (
        await Promise.all(
            drafts.value.map((d) => request(`/api/v1/generation/drafts/${d.id}/releases`))
        )
    ).flat()
}
async function refresh() {
    await action(async () => {
        if (!props.project) tab.value = 'admin'
        else {
            batches.value = await request('/api/v1/team-data/reviews')
            if (canDevelop.value) {
                if (tab.value === 'sources') await loadSources()
                if (['reviews', 'exports'].includes(tab.value)) await loadChoices()
                if (tab.value === 'exports')
                    exports.value = await request('/api/v1/team-data/exports')
            }
        }
        if (tab.value === 'admin') {
            if (props.user.admin){users.value = await request('/team/users');allProjects.value=await request('/team/admin/projects')}
            if (props.project && roles.value.includes('manage')) {
                members.value = await request(`/team/projects/${props.project.id}/members`)
                audit.value = await request(`/team/audit?project=${props.project.id}`)
            }
        }
    })
}
async function createReview() {
    await action(async () => {
        const r = await request('/api/v1/team-data/reviews', {
            ...reviewForm.value,
            kind: choices.value.find((d) => d.id === reviewForm.value.source)?.kind || 'draft',
            count: reviewForm.value.count || undefined,
            template: JSON.parse(templateJson.value),
            reviewers: selectedReviewers.value,
            request_id: uuid()
        })
        await openRaw(r.id)
    })
}
async function openRaw(id) {
    batch.value = await request(`/api/v1/team-data/reviews/${id}`)
    index.value = 0
    loadItem()
}
async function openBatch(id) {
    await action(() => openRaw(id))
}
function loadItem() {
    const d = item.value?.decision || item.value?.saved || {}
    scores.value = {}
    unknown.value = {}
    for (const [k, v] of Object.entries(d.scores || {})) {
        scores.value[k] = typeof v === 'object' ? 'unknown' : v
        if (typeof v === 'object') unknown.value[k] = v.unknown
    }
    conclusion.value = d.conclusion || ''
    comment.value = d.comment || ''
    tags.value = d.tags || []
    revised.value = JSON.stringify(item.value?.row || {}, null, 2)
    reason.value = ''
    baseline.value = formState()
}
function selectItem(n) {
    if (!discard()) return
    index.value = n
    loadItem()
}
function leaveBatch() {
    if (!discard()) return
    batch.value = null
    refresh()
}
function decision() {
    return {
        scores: Object.fromEntries(
            Object.entries(scores.value)
                .filter(([, v]) => v !== '')
                .map(([k, v]) => [
                    k,
                    v === 'unknown' ? { unknown: unknown.value[k] || '' } : Number(v)
                ])
        ),
        conclusion: conclusion.value,
        comment: comment.value,
        tags: tags.value
    }
}
async function itemRaw(operation, extra = {}) {
    const n = index.value,
        id = batch.value.id
    await request(`/api/v1/team-data/reviews/${id}/items/${item.value.id}/${operation}`, {
        version: item.value.version,
        request_id: uuid(),
        ...extra
    })
    batch.value = await request(`/api/v1/team-data/reviews/${id}`)
    index.value = n
    loadItem()
}
async function actItem(operation, extra = {}) {
    await action(() => itemRaw(operation, extra))
}
async function save(skipped) {
    await action(async () => {
        await itemRaw('save', { draft: decision(), skipped })
        notice.value = skipped ? '已标记稍后处理，不计入完成。' : '进度已保存。'
    })
}
async function submit() {
    await action(async () => {
        await itemRaw('submit', decision())
        notice.value = '评测已提交。'
    })
}
async function revise() {
    await action(() =>
        itemRaw('revise', {
            ...decision(),
            conclusion: 'pass',
            row: JSON.parse(revised.value),
            reason: reason.value
        })
    )
}
async function reopen() {
    const why = window.prompt('重开原因')
    if (why) await actItem('reopen', { reason: why })
}
async function closeBatch() {
    if (!window.confirm('关闭后保留已有结果，停止未完成项。继续？')) return
    await action(async () => {
        await request(`/api/v1/team-data/reviews/${batch.value.id}/close`, {
            version: batch.value.version
        })
        await openRaw(batch.value.id)
    })
}
async function derive() {
    await action(async () => {
        const d = await request(`/api/v1/team-data/reviews/${batch.value.id}/derive`, {})
        notice.value = `已创建「${d.name}」，可在生成数据集发布。`
    })
}
function exportBody() {
    return {
        ...exportForm.value,
        kind: choices.value.find((d) => d.id === exportForm.value.source)?.kind || 'draft',
        batch: exportForm.value.batch || undefined,
        mapping: JSON.parse(mapping.value),
        media_policy: referencesOnly.value ? 'references_only' : undefined
    }
}
async function previewExport() {
    await action(async () => {
        if (exportForm.value.format.startsWith('review_')) {
            if (!exportForm.value.batch) throw new Error('请选择批次')
            preview.value = { total: 0, compatible: 0, errors: [], output_fields: ['评测明细'] }
        } else preview.value = await request('/api/v1/team-data/exports/preview', exportBody())
    })
}
async function createExport() {
    await action(async () => {
        if (preview.value?.errors?.length) throw new Error('请修复不兼容样本')
        const r = await request('/api/v1/team-data/exports', {
            ...exportBody(),
            request_id: uuid()
        })
        exports.value = await request('/api/v1/team-data/exports')
        if (r.status === 'failed') throw new Error(r.error)
        notice.value = '快照已固定，可在下方下载。'
    })
}
async function expireExport(id){if(!window.confirm('只清理此导出的临时文件，发布版本和原始材料保留。继续？'))return;await action(async()=>{await request(`/api/v1/team-data/exports/${id}/expire`,{});exports.value=await request('/api/v1/team-data/exports')})}
async function invite() {
    await action(async () => {
        const r = await request('/team/invitations', { name: accountName.value })
        inviteToken.value = r.invitation
        users.value = await request('/team/users')
        accountName.value = ''
    })
}
async function toggleUser(u) {
    await action(async () => {
        await request(`/team/users/${u.id}/enabled`, { enabled: !u.enabled })
        users.value = await request('/team/users')
    })
}
async function resetUser(u) {
    await action(async () => {
        const r = await request('/team/invitations', { reset: u.id })
        inviteToken.value = r.invitation
    })
}
async function adminEnter(id){if(!window.confirm('以系统管理员身份进入此项目，操作会记录在审计中。继续？'))return;await action(async()=>{await request(`/team/admin/projects/${id}/enter`,{});window.location.reload()})}
async function newProject() {
    await action(async () => {
        await request('/team/projects', { name: projectName.value })
        projectName.value = ''
        emit('refresh')
        notice.value = '项目已创建，可在顶部切换。'
    })
}
async function saveMember() {
    await action(async () => {
        await request(
            `/team/projects/${props.project.id}/members/${memberForm.value.user}`,
            { roles: memberForm.value.roles, version: memberForm.value.version },
            'PUT'
        )
        members.value = await request(`/team/projects/${props.project.id}/members`)
        memberForm.value = { user: '', roles: [], version: 0 }
    })
}
async function changePassword() {
    await action(async () => {
        await request('/team/password', {
            current: currentPassword.value,
            password: newPassword.value
        })
        window.location.reload()
    })
}
watch(
    [exportForm, mapping, referencesOnly],
    () => {
        preview.value = null
    },
    { deep: true }
)
watch(
    () => props.selection,
    (value) => {
        if (value) {
            tab.value = value.tab || 'reviews'
            if(value.tab==='sources'){expanded.value=value.source||'';if(value.source){filter.value='';offset.value=0}}
            reviewForm.value.source = value.source || ''
            exportForm.value.source = value.source || ''
            refresh()
        }
    },
    { immediate: true }
)
const beforeLeave = (e) => {
    if (dirty.value) {
        e.preventDefault()
        e.returnValue = ''
    }
}
const workspaceLeave=e=>{if(!discard())e.preventDefault()}
onMounted(() => {
    window.addEventListener('dataflow-before-workspace-change',workspaceLeave)
    window.addEventListener('beforeunload', beforeLeave)
    refresh()
})
onBeforeUnmount(() => {window.removeEventListener('beforeunload', beforeLeave);window.removeEventListener('dataflow-before-workspace-change',workspaceLeave)})
</script>
<style scoped>
.workspace {
    max-width: 1440px;
    margin: auto;
    padding: 30px 40px 70px;
    font-size: 14px;
    line-height: 1.6;
}
header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
}
h1 {
    font-size: 26px;
    font-weight: 600;
    margin: 5px 0;
}
header p,
small {
    color: var(--team-muted);
}
h2 {
    font-size: 17px;
    margin-bottom: 16px;
}
h3 {
    font-size: 14px;
    margin-bottom: 16px;
}
.tabs {
    display: flex;
    gap: 12px;
    border-bottom: 1px solid var(--team-border);
    padding-bottom: 12px;
    margin-bottom: 24px;
}
.tabs button {
    border-color: transparent;
}
.tools {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
    margin: 16px 0;
}
.tools > span:last-child {
    margin-left: auto;
}
.card,
.table-wrap {
    background: var(--team-panel);
    border: 1px solid var(--team-border);
    border-radius: 9px;
    overflow: hidden;
}
.card {
    padding: 22px;
    margin-bottom: 22px;
}
summary {
    cursor: pointer;
    font-weight: 500;
}
table {
    width: 100%;
    border-collapse: collapse;
    text-align: left;
}
th,
td {
    padding: 14px 18px;
    border-bottom: 1px solid var(--team-border);
    vertical-align: middle;
}
th {
    font-size: 12px;
    font-weight: 500;
    color: var(--team-muted);
    background: color-mix(in srgb, var(--team-border) 22%, transparent);
}
tr:last-child td {
    border-bottom: 0;
}
td small {
    display: block;
    font-size: 11px;
}
td button {
    margin-left: 8px;
}
a {
    color: var(--team-accent);
    text-decoration: none;
}
a:hover {
    text-decoration: underline;
}
.badge {
    display: inline-block;
    padding: 2px 8px;
    font-size: 12px;
    border-radius: 4px;
    background: #eef0fc;
    color: #5263bd;
    margin: 2px 5px 2px 0;
}
.good {
    color: #267159;
    background: #eaf6f0;
}
.warn {
    color: #966526;
    background: #fff4df;
}
.detail {
    background: color-mix(in srgb, var(--team-border) 12%, transparent);
}
.detail p {
    margin: 8px 0;
}
.grid,
.columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px 24px;
}
.wide {
    grid-column: 1/-1;
}
form {
    margin-top: 16px;
}
label {
    display: grid;
    gap: 7px;
    font-size: 13px;
    margin-bottom: 14px;
}
input,
textarea {
    font: inherit;
    color: inherit;
    background: var(--team-panel);
    border: 1px solid var(--team-border);
    border-radius: 6px;
    padding: 9px 12px;
    width: 100%;
}
select {
    width: 100%;
}
textarea {
    resize: vertical;
}
.check {
    display: flex;
    gap: 8px;
    align-items: center;
}
.check input {
    width: auto;
}
.feedback {
    padding: 12px 16px;
    margin: 14px 0;
    background: color-mix(in srgb, var(--team-accent) 6%, var(--team-panel));
    border-radius: 6px;
    overflow-wrap: anywhere;
}
.empty {
    padding: 48px;
    text-align: center;
    color: var(--team-muted);
}
.pager {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 20px;
    margin-top: 20px;
}
.metrics {
    display: flex;
    gap: 40px;
    flex-wrap: wrap;
    background: var(--team-panel);
    border: 1px solid var(--team-border);
    border-radius: 9px;
    padding: 20px 25px;
    margin: 20px 0;
}
.metrics div {
    display: grid;
}
.metrics b {
    font-size: 24px;
    font-weight: 600;
}
.metrics span {
    font-size: 12px;
    color: var(--team-muted);
}
.workbench {
    display: grid;
    grid-template-columns: 170px minmax(0, 1fr);
    gap: 22px;
}
.workbench aside {
    display: flex;
    flex-direction: column;
    gap: 5px;
    max-height: 650px;
    overflow: auto;
}
.workbench aside button {
    display: flex;
    justify-content: space-between;
    border-color: transparent;
}
.workbench aside small {
    font-size: 11px;
}
.review-body {
    min-width: 0;
}
.columns > .card {
    min-width: 0;
    max-height: 650px;
    overflow: auto;
}
.columns img {
    max-width: 100%;
    max-height: 420px;
    object-fit: contain;
    border-radius: 5px;
}
.field {
    margin-bottom: 20px;
}
.preserve {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    margin-top: 7px;
}
fieldset {
    border: 0;
    min-width: 0;
}
legend {
    font-size: 17px;
    font-weight: 500;
    margin-bottom: 18px;
}
.score {
    display: flex;
    gap: 16px;
    align-items: center;
    margin-bottom: 14px;
}
.score label {
    width: 170px;
    margin: 0;
}
.score select {
    max-width: 140px;
}
.score input {
    flex: 1;
}
details label {
    margin-top: 14px;
}
pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-height: 350px;
    overflow: auto;
    padding: 14px;
    font-size: 12px;
}
code {
    display: block;
    overflow-wrap: anywhere;
}
button:disabled,
fieldset:disabled {
    opacity: 0.55;
}
button:disabled {
    cursor: default;
}
@media (max-width: 900px) {
    .workspace {
        padding: 24px 18px;
    }
    .grid,
    .columns,
    .workbench {
        grid-template-columns: 1fr;
    }
    .wide {
        grid-column: auto;
    }
    .workbench aside {
        flex-direction: row;
        max-height: 70px;
    }
    .workbench aside button {
        min-width: 130px;
    }
    .metrics {
        gap: 20px;
    }
    .table-wrap {
        overflow-x: auto;
    }
    .score {
        flex-wrap: wrap;
    }
}
</style>

<style scoped>.context-frame{width:100%;height:280px;border:1px solid var(--team-border);border-radius:6px;background:white;margin:10px 0}select[multiple]{min-height:90px}</style>

<style scoped>.table-wrap table{min-width:760px}.table-wrap th,.table-wrap td button{white-space:nowrap}</style>
