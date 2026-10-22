<template>
    <base-panel v-model="thisValue" title="原始数据集" width="900px" height="80%" :theme="theme">
        <template #content
            ><common-dataset v-if="thisValue" @confirm="$emit('confirm', $event)"
        /></template>
        <template #control="{ close }"
            ><fv-button :theme="theme" border-radius="8" style="width: 100px" @click="close"
                >关闭</fv-button
            ></template
        >
    </base-panel>
</template>
<script>
import { mapState } from 'pinia'
import { useTheme } from '@/stores/theme'
import BasePanel from '@/components/general/basePanel.vue'
import CommonDataset from './commonDataset/index.vue'
export default {
    name: 'SourceDatasetPanel',
    components: { BasePanel, CommonDataset },
    props: { modelValue: { type: Boolean, default: false } },
    emits: ['update:modelValue', 'confirm'],
    computed: {
        ...mapState(useTheme, ['theme']),
        thisValue: {
            get() {
                return this.modelValue
            },
            set(value) {
                this.$emit('update:modelValue', value)
            }
        }
    }
}
</script>
