<template>
    <div class="catalog-filter-bar">
        <div class="filter-fields">
            <label class="filter-search"><span>名称搜索</span><native-text :model-value="modelValue.search" :theme="theme" label="搜索数据集" placeholder="搜索数据集名称" @update:modelValue="set('search', $event)" /></label>
            <label v-for="field in fields" :key="field.key"><span>{{ field.label }}</span><native-select :model-value="modelValue[field.key]" :theme="theme" :label="field.label" :options="field.options" @update:modelValue="set(field.key, $event)" /></label>
            <label><span>排序</span><native-select :model-value="modelValue.sort" :theme="theme" label="排序" :options="sorts" @update:modelValue="set('sort', $event)" /></label>
        </div>
        <div class="filter-summary">
            <span class="match-count" role="status" aria-live="polite">匹配 {{ count }} / 共 {{ total }} 个</span>
            <fv-button v-if="active.length || modelValue.sort !== 'recent'" :theme="theme" :border-radius="6" class="clear-filters" @click="clear">清空筛选</fv-button>
        </div>
        <div v-if="active.length" class="filter-tags" aria-label="已选筛选条件">
            <button v-for="item in active" :key="item.key" type="button" :aria-label="`移除${item.label}`" @click="set(item.key, '')">{{ item.label }}<i class="ms-Icon ms-Icon--Cancel" aria-hidden="true"></i></button>
        </div>
    </div>
</template>
<script>
import NativeText from '@/components/manage/forms/NativeText.vue'
import NativeSelect from '@/components/manage/forms/NativeSelect.vue'
import { defaultFilters, filterFields, activeFilters, sortOptions } from '@/views/manage/library/filters.js'
export default {
    components: { NativeText, NativeSelect },
    props: { modelValue: { type: Object, required: true }, mode: { type: String, required: true }, theme: String, count: Number, total: Number },
    emits: ['update:modelValue'],
    computed: {
        fields() { return filterFields(this.mode) },
        active() { return activeFilters(this.modelValue, this.mode) },
        sorts() { return this.mode === 'materials' ? sortOptions : [...sortOptions, { value: 'samples', label: '样本数从多到少' }] }
    },
    methods: {
        set(key, value) { this.$emit('update:modelValue', { ...this.modelValue, [key]: value }) },
        clear() { this.$emit('update:modelValue', defaultFilters()) }
    }
}
</script>
<style scoped>
.catalog-filter-bar { padding: 20px; border-bottom: 1px solid rgba(120,120,120,.14); }
.filter-fields { display: flex; flex-wrap: wrap; gap: 14px; align-items: end; }
.filter-fields label { display: flex; flex: 1 1 150px; flex-direction: column; gap: 6px; min-width: 0; max-width: 240px; margin: 0; }
.filter-fields .filter-search { flex: 2 1 240px; max-width: 360px; }
label > span { color: #78849a; font-size: 12px; line-height: 1.5; }
.filter-summary { display: flex; align-items: center; gap: 12px; min-height: 32px; margin-top: 14px; }
.match-count { color: #78849a; font-size: 13px; font-variant-numeric: tabular-nums; }
.clear-filters { width: 96px; height: 30px; }
.filter-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.filter-tags button { display: inline-flex; align-items: center; gap: 10px; max-width: 100%; padding: 5px 9px; border: 1px solid rgba(78,91,213,.2); border-radius: 6px; background: rgba(78,91,213,.07); color: inherit; font-size: 12px; text-align: left; overflow-wrap: anywhere; cursor: pointer; }
.filter-tags button:hover { background: rgba(78,91,213,.14); }
.filter-tags i { flex-shrink: 0; font-size: 10px; }
@container library (max-width: 600px) { .catalog-filter-bar { padding: 14px 12px; } .filter-fields label { max-width: none; } }
</style>
