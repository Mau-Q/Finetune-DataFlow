<template>
    <baseDrawer v-model="thisValue" :title="title" length="min(480px, 100vw)" :theme="theme">
        <template #content>
            <section v-if="thisValue" class="operator-catalog" :class="{ dark: theme === 'dark' }" aria-label="算子库">
                <nav class="catalog-tabs" aria-label="算子类型">
                    <button v-for="item in categories" :key="item.key" type="button"
                        :aria-pressed="category === item.key" :class="{ active: category === item.key }"
                        @click="category = item.key">{{ item.name }}</button>
                </nav>
                <div class="catalog-library-tools">
                    <select v-model="groupFilter" aria-label="算子分组"><option value="">全部分组</option><option v-for="group in availableGroups" :key="group.key" :value="group.key">{{ group.name }}</option></select>
                    <div class="catalog-shortcuts"><button v-for="item in shortcuts" :key="item.key" :class="{ active: scope === item.key }" :aria-pressed="scope === item.key" @click="scope = item.key">{{ item.label }}</button></div>
                </div>
                <div class="catalog-search">
                    <i class="ms-Icon ms-Icon--Search" aria-hidden="true"></i>
                    <input v-model="searchText" type="search" aria-label="搜索算子" :placeholder="local('Search Operators ...')" />
                </div>
                <div class="catalog-meta"><span>{{ totalVisible }} {{ language === 'cn' ? '个算子' : 'operators' }}</span>
                    <span>{{ language === 'cn' ? '拖动到画布 · 点击查看说明' : 'Drag to canvas · Click for details' }}</span></div>
                <div class="catalog-scroll">
                    <p v-if="loading" class="catalog-empty" role="status">{{ language === 'cn' ? '正在加载算子…' : 'Loading operators…' }}</p>
                    <div v-else-if="loadError" class="catalog-empty" role="alert">{{ loadError }}<button @click="loadOperators">{{ language === 'cn' ? '重试' : 'Retry' }}</button></div>
                    <template v-else>
                        <details v-for="group in visibleGroups" :key="group.key" class="catalog-group" open>
                            <summary><span>{{ group.name }}</span><span class="group-count">{{ group.items.length }}</span></summary>
                            <article v-for="op in group.items" :key="op.name || op.label" class="catalog-row"
                                :class="{ expanded: expandedOperator === op.label }">
                                <button type="button" class="operator-overview" draggable="true"
                                    :aria-expanded="expandedOperator === op.label"
                                    @dragstart="dragStart($event, op)" @click="toggleDetails(op)">
                                    <span class="operator-type-icon" :style="{ color: op.borderColor }"><i class="ms-Icon" :class="'ms-Icon--' + (op.icon || 'Processing')" aria-hidden="true"></i></span>
                                    <span class="operator-overview-text"><span class="operator-title" :title="op.label">{{ op.label }}</span>
                                        <span class="operator-summary">{{ summary(op) }}</span></span>
                                    <span class="operator-kind">{{ typeName(op.type?.level_2) }}</span>
                                    <span class="operator-chevron" aria-hidden="true">{{ expandedOperator === op.label ? '−' : '+' }}</span>
                                </button>
                                <div class="operator-actions">
                                    <button class="favorite-button" :aria-pressed="favorites.includes(op.label)" :aria-label="`${favorites.includes(op.label) ? '取消收藏' : '收藏'} ${op.label}`" @click="toggleFavorite(op)">{{ favorites.includes(op.label) ? '★' : '☆' }}</button>
                                    <fv-button :theme="theme" :border-radius="6" :aria-label="`添加 ${op.label} 到画布`" @click="addOperator(op)">＋ 添加</fv-button>
                                </div>
                                <div v-if="expandedOperator === op.label" class="operator-documentation">
                                    <mdTextBlock :modelValue="op.description || (language === 'cn' ? '暂无说明' : 'No description')" />
                                    <button class="collapse-description" @click="expandedOperator = ''">收起说明 ↑</button>
                                </div>
                            </article>
                        </details>
                        <div v-if="!totalVisible" class="catalog-empty" role="status">
                            <p>{{ language === 'cn' ? '没有匹配的算子' : 'No matching operators' }}</p>
                            <button v-if="searchText || category !== 'all' || groupFilter || scope !== 'all'" @click="searchText = ''; category = 'all'; groupFilter = ''; scope = 'all'">{{ language === 'cn' ? '清除筛选' : 'Clear filters' }}</button>
                        </div>
                    </template>
                </div>
            </section>
        </template>
        <template #control="{ close }">
            <fv-button :theme="theme" :borderRadius="8" style="width: 100px" @click="close">{{ local('Close') }}</fv-button>
        </template>
    </baseDrawer>
</template>

<script>
import { mapState, mapActions } from 'pinia'
import { useAppConfig } from '@/stores/appConfig'
import { useDataflow } from '@/stores/dataflow'
import { useTheme } from '@/stores/theme'
import { readWorkspaceState, writeWorkspaceState } from '@/hooks/dataflow/workspaceState'
import baseDrawer from '@/components/general/baseDrawer.vue'
import mdTextBlock from '@/components/general/mdTextBlock.vue'

export default {
    components: { baseDrawer, mdTextBlock },
    props: { modelValue: { default: false }, title: { default: '算子库' } },
    emits: ['update:modelValue', 'add'],
    data() {
        return { thisValue: this.modelValue, searchText: '', category: 'all', expandedOperator: '', groupFilter: '', scope: 'all', favorites: [], recent: [], loading: false, loadError: '' }
    },
    computed: {
        ...mapState(useAppConfig, ['local', 'language']),
        ...mapState(useDataflow, ['groupOperators']),
        ...mapState(useTheme, ['theme']),
        categories() {
            return [['all', 'All'], ['filter', 'Filter'], ['generate', 'Generate'], ['eval', 'Evaluate'], ['refine', 'Refine']]
                .map(([key, name]) => ({ key, name: key === 'refine' && this.language === 'cn' ? '改写与整理' : this.local(name) }))
        },
        shortcuts() { return [{key:'all',label:'全部'}, {key:'recent',label:'最近'}, {key:'favorites',label:'收藏'}] },
        availableGroups() { return Object.values(this.groupOperators).map(({key,name}) => ({key,name})) },
        libraryPreferences() { return { searchText: this.searchText, category: this.category, groupFilter: this.groupFilter, scope: this.scope, favorites: this.favorites, recent: this.recent } },
        visibleGroups() {
            const query = this.searchText.trim().toLowerCase()
            return Object.values(this.groupOperators).filter(group => !this.groupFilter || group.key === this.groupFilter).map(group => ({ ...group, items: group.items.filter(op => {
                const type = op.type?.level_2 || ''
                return (this.scope === 'all' || (this.scope === 'favorites' ? this.favorites : this.recent).includes(op.label)) && (this.category === 'all' || type === this.category) &&
                    (!query || [op.label, op.name, op.status, op.type?.level_1, type, this.typeName(type), op.description]
                        .some(value => String(value || '').toLowerCase().includes(query)))
            }) })).map(group => ({ ...group, items: this.scope === 'recent' ? group.items.slice().sort((a,b) => this.recent.indexOf(a.label) - this.recent.indexOf(b.label)) : group.items })).filter(group => group.items.length)
        },
        totalVisible() { return this.visibleGroups.reduce((total, group) => total + group.items.length, 0) }
    },
    watch: {
        libraryPreferences: { deep: true, handler(value) { writeWorkspaceState('operator-library', value) } },
        modelValue(value) { this.thisValue = value; if (value) this.loadOperators() },
        thisValue(value) { this.$emit('update:modelValue', value) }
    },
    mounted() {
        const saved = readWorkspaceState('operator-library', {})
        for (const key of ['searchText','category','groupFilter','scope']) if (typeof saved[key] === 'string') this[key] = saved[key]
        for (const key of ['favorites','recent']) if (Array.isArray(saved[key])) this[key] = saved[key].filter(value => typeof value === 'string')
        if (this.modelValue) this.loadOperators()
    },
    methods: {
        ...mapActions(useDataflow, ['getOperators']),
        async loadOperators() {
            this.loading = true
            this.loadError = ''
            try { await this.getOperators(this.language === 'cn' ? 'zh' : 'en') }
            catch (error) { this.loadError = this.language === 'cn' ? '算子加载失败，请重试。' : 'Unable to load operators. Please retry.' }
            finally { this.loading = false }
        },
        rememberOperator(op) { this.recent = [op.label, ...this.recent.filter(name => name !== op.label)].slice(0, 12) },
        toggleFavorite(op) { this.favorites = this.favorites.includes(op.label) ? this.favorites.filter(name => name !== op.label) : [...this.favorites, op.label] },
        addOperator(op) { this.rememberOperator(op); this.$emit('add', op); this.thisValue = false },
        typeName(type) {
            const names = { filter: 'Filter', generate: 'Generate', eval: 'Evaluate', refine: 'Refine', parser: 'Parser' }
            return names[type] ? this.local(names[type]) : (this.language === 'cn' ? '自定义' : 'Custom')
        },
        summary(op) {
            return String(op.description || '').replace(/<[^>]*>/g, '').replace(/[#*`>]/g, '')
                .split(/输入参数[：:]|输出参数[：:]|使用场景[：:]|\n/)[0].replace(/\s+/g, ' ').trim().slice(0, 160) || op.status || ''
        },
        toggleDetails(op) { this.expandedOperator = this.expandedOperator === op.label ? '' : op.label },
        dragStart(event, item) {
            this.rememberOperator(item)
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'copy'
                event.dataTransfer.setData('application/vueflow', JSON.stringify(item))
                event.dataTransfer.setData('event/offsetX', String(event.offsetX))
            }
        }
    }
}
</script>

<style scoped lang="scss">
.operator-catalog {
    --catalog-text: #263047;
    --catalog-muted: #747e90;
    --catalog-border: #e5e7ee;
    --catalog-panel: #fff;
    --catalog-accent: #5c59d5;
    --catalog-hover: #f1f2fc;
    color: var(--catalog-text);
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
    gap: 14px;
    &.dark {
        --catalog-text: #e4e7f0;
        --catalog-muted: #a0a8bb;
        --catalog-border: #3a3e4b;
        --catalog-panel: #252833;
        --catalog-accent: #b3b0ff;
        --catalog-hover: #32354b;
    }
    button, input { font: inherit; color: inherit; }
    button { cursor: pointer; }
    button:focus-visible, input:focus-visible, summary:focus-visible { outline: 2px solid var(--catalog-accent); outline-offset: 2px; }
}
.catalog-tabs {
    display: flex;
    gap: 4px;
    flex-shrink: 0;
    button {
        flex: 1;
        padding: 8px 4px;
        font-size: 13px;
        border: 0;
        border-radius: 7px;
        background: transparent;
        color: var(--catalog-muted);
        &.active { background: var(--catalog-hover); color: var(--catalog-accent); font-weight: 600; }
        &:hover { background: var(--catalog-hover); }
    }
}
.catalog-library-tools { display:flex; gap:10px; justify-content:space-between; align-items:center; flex-wrap:wrap; flex-shrink:0; select { flex:1; min-width:100px; max-width:200px; border:1px solid var(--catalog-border); border-radius:6px; padding:6px; background:var(--catalog-panel); color:inherit; font:inherit; font-size:12px; } }
.catalog-shortcuts { display:flex; gap:3px; button { border:0; border-radius:5px; padding:6px 8px; background:transparent; color:var(--catalog-muted); font-size:12px; &.active { color:var(--catalog-accent); background:var(--catalog-hover); } } }
.operator-actions { display:flex; justify-content:flex-end; gap:8px; align-items:center; padding:0 6px 8px; .favorite-button { border:0; background:transparent; color:var(--catalog-accent); padding:4px 7px; font-size:20px; line-height:1; } .fv-button { height:26px; min-width:70px; font-size:11px; } }
.collapse-description { margin-top:12px; border:0; background:transparent; color:var(--catalog-accent); padding:4px 0; font-size:12px; }
.catalog-search {
    display: flex;
    align-items: center;
    gap: 9px;
    flex-shrink: 0;
    border: 1px solid var(--catalog-border);
    border-radius: 8px;
    background: var(--catalog-panel);
    padding: 0 12px;
    color: var(--catalog-muted);
    &:focus-within { border-color: var(--catalog-accent); }
    input { width: 100%; min-width: 0; height: 38px; border: 0; outline: none; background: transparent; font-size: 13px; }
}
.catalog-meta { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 6px; color: var(--catalog-muted); font-size: 11px; flex-shrink: 0; }
.catalog-scroll { flex: 1; min-height: 0; overflow-y: auto; padding-right: 4px; }
.catalog-group {
    margin-bottom: 16px;
    > summary { display: flex; align-items: center; gap: 8px; padding: 8px 2px; cursor: pointer; font-size: 12px; font-weight: 600; list-style: none; }
    > summary::-webkit-details-marker { display: none; }
    > summary::before { content: '›'; font-size: 17px; color: var(--catalog-muted); transform: rotate(0); }
    &[open] > summary::before { transform: rotate(90deg); }
    .group-count { color: var(--catalog-muted); font-size: 11px; font-weight: 400; }
}
.catalog-row { border-bottom: 1px solid var(--catalog-border); }
.operator-overview {
    display: flex;
    align-items: flex-start;
    width: 100%;
    gap: 10px;
    padding: 13px 6px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    text-align: left;
    cursor: grab !important;
    &:hover { background: var(--catalog-hover); }
    &:active { cursor: grabbing !important; }
}
.operator-type-icon { display: grid; place-items: center; width: 28px; height: 28px; flex-shrink: 0; border: 1px solid var(--catalog-border); border-radius: 7px; font-size: 14px; }
.operator-overview-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.operator-title { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; line-height: 1.45; }
.operator-summary { font-size: 12px; color: var(--catalog-muted); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.operator-kind { flex-shrink: 0; color: var(--catalog-muted); font-size: 10px; padding-top: 3px; }
.operator-chevron { font-size: 15px; color: var(--catalog-muted); width: 12px; flex-shrink: 0; text-align: center; }
.operator-documentation { margin: 0 6px 12px; padding: 14px; border: 1px solid var(--catalog-border); border-radius: 7px; background: var(--catalog-panel); font-size: 12px; line-height: 1.8; overflow-wrap: anywhere; }
.operator-documentation :deep(.md-text-default-block) { color: var(--catalog-text); }
.operator-documentation :deep(p + p) { margin-top: 10px; }
.operator-documentation :deep(pre) { max-width: 100%; overflow: auto; }
.catalog-empty { padding: 40px 15px; text-align: center; font-size: 13px; color: var(--catalog-muted); }
.catalog-empty button { display: block; margin: 14px auto 0; padding: 7px 12px; border: 1px solid var(--catalog-border); border-radius: 6px; background: var(--catalog-panel); color: var(--catalog-accent); }
@media(max-width:480px) { .operator-overview { gap: 7px; } .operator-type-icon { display: none; } }
</style>
