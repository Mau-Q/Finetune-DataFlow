<template>
    <div>
        <article v-for="(s, i) in modelValue" :key="i">
            <h3>阶段 {{ i + 1 }}</h3>
            <div class="grid">
                <label
                    >类别<native-select
                        :model-value="s.family"
                        @update:modelValue="update(i, { family: $event, component: '' })"
                        :options="families"
                        :theme="theme"
                        label="阶段类别" /></label
                ><label
                    >组件<native-select
                        :model-value="s.component"
                        @update:modelValue="update(i, { component: $event })"
                        :options="choices(s.family)"
                        :theme="theme"
                        label="阶段组件" /></label
                ><label
                    >更新频率<input
                        type="number"
                        min="1"
                        :value="s.every ?? 1"
                        @input="update(i, { every: Number($event.target.value) })" /></label
                ><label
                    >预热步数<input
                        type="number"
                        min="0"
                        :value="s.warmup_step ?? 0"
                        @input="update(i, { warmup_step: Number($event.target.value) })" /></label
                ><label v-if="s.family === 'selector'"
                    >选择方式<native-select
                        :model-value="s.mode || 'filter'"
                        @update:modelValue="update(i, { mode: $event })"
                        :options="['filter', 'draw']"
                        :theme="theme"
                        label="阶段选择方式" /></label
                ><label v-if="s.family === 'selector'"
                    >保留比例<input
                        type="number"
                        min="0.001"
                        max="1"
                        step="0.05"
                        :value="s.keep_ratio ?? 1"
                        @input="update(i, { keep_ratio: Number($event.target.value) })"
                /></label>
            </div>
            <label
                ><input
                    type="checkbox"
                    :checked="s.enabled !== false"
                    @change="update(i, { enabled: $event.target.checked })"
                />启用此阶段</label
            ><button @click="remove(i)">移除阶段</button>
        </article>
        <button @click="add">添加阶段</button>
    </div>
</template>
<script>
import NativeSelect from '@/components/manage/forms/NativeSelect.vue'
export default {
    components: { NativeSelect },
    props: { modelValue: { type: Array, default: () => [] }, components: Array, theme: String },
    emits: ['update:modelValue'],
    data: () => ({ families: ['selector', 'mixer', 'reorder', 'weighter'] }),
    methods: {
        choices(f) {
            const family = {
                selector: 'selection',
                mixer: 'mixture',
                reorder: 'reorder',
                weighter: 'reweighting'
            }[f]
            return this.components.filter((c) => c.family === family).map((c) => c.name)
        },
        update(i, v) {
            this.$emit(
                'update:modelValue',
                this.modelValue.map((s, k) => (k === i ? { ...s, ...v } : s))
            )
        },
        add() {
            this.$emit('update:modelValue', [
                ...this.modelValue,
                { family: 'weighter', component: 'loss', every: 1, warmup_step: 0, enabled: true }
            ])
        },
        remove(i) {
            this.$emit(
                'update:modelValue',
                this.modelValue.filter((_, k) => k !== i)
            )
        }
    }
}
</script>
<style scoped>
article {
    padding: 12px 0 20px;
    border-top: 1px solid #c5cbd8;
}
.grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
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
    border: 1px solid #a7aebc;
    border-radius: 6px;
    padding: 9px;
    box-sizing: border-box;
}
input {
    width: 100%;
}
input[type='checkbox'] {
    width: auto;
}
button {
    cursor: pointer;
}
@media (max-width: 800px) {
    .grid {
        grid-template-columns: 1fr;
    }
}
</style>
