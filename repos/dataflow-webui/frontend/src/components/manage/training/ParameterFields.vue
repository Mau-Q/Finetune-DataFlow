<template>
    <div class="fields">
        <label v-for="(field, key) in fields" :key="key"
            >{{ key }}
            <small
                >{{ field.type
                }}{{ field.minimum !== undefined ? ' · 最小 ' + field.minimum : '' }}</small
            ><input
                v-if="['number', 'integer'].includes(field.type)"
                type="number"
                :value="value(key, field)"
                :step="field.type === 'integer' ? '1' : 'any'"
                @input="set(key, Number($event.target.value))"
                :aria-label="'参数 ' + key"
            /><input
                v-else-if="field.type === 'boolean'"
                type="checkbox"
                :checked="value(key, field)"
                @change="set(key, $event.target.checked)"
                :aria-label="'参数 ' + key"
            /><native-text
                v-else-if="field.type === 'string'"
                :model-value="value(key, field)"
                @update:modelValue="set(key, $event)"
                :theme="theme"
                :label="'参数 ' + key"
            /><template v-else
                ><native-text
                    :model-value="json(value(key, field))"
                    multiline
                    code
                    :rows="4"
                    :theme="theme"
                    :label="'参数 ' + key"
                    @update:modelValue="parse(key, $event)"
                /><span role="alert" v-if="errors[key]">{{ errors[key] }}</span></template
            ></label
        >
    </div>
</template>
<script>
import NativeText from '@/components/manage/forms/NativeText.vue'
export default {
    components: { NativeText },
    props: ['modelValue', 'fields', 'theme'],
    emits: ['update:modelValue', 'invalid'],
    data: () => ({ errors: {} }),
    methods: {
        value(k, f) {
            return Object.hasOwn(this.modelValue, k) ? this.modelValue[k] : f.default
        },
        set(k, v) {
            this.$emit('update:modelValue', { ...this.modelValue, [k]: v })
        },
        json(v) {
            return JSON.stringify(v, null, 2)
        },
        parse(k, t) {
            try {
                const v = JSON.parse(t)
                this.errors[k] = ''
                this.set(k, v)
            } catch {
                this.errors[k] = 'JSON 未完成，尚未应用'
            }
            this.$emit('invalid', Object.values(this.errors).some(Boolean))
        }
    }
}
</script>
<style scoped>
.fields {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px 20px;
}
label {
    display: block;
    line-height: 2;
}
small {
    opacity: 0.65;
}
input {
    width: 100%;
    font: inherit;
    color: inherit;
    background: transparent;
    border: 1px solid #a7aebc;
    border-radius: 6px;
    padding: 9px;
    box-sizing: border-box;
}
input[type='checkbox'] {
    width: auto;
    display: block;
}
span {
    color: #ae342b;
}
@media (max-width: 800px) {
    .fields {
        grid-template-columns: 1fr;
    }
}
</style>
