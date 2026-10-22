<template><component :is="multiline ? 'fv-text-field' : 'fv-text-box'" v-model="value" :theme="theme" :disabled="disabled" :placeholder="placeholder" :aria-label="label" :border-radius="6" :style="{width:'100%',height:multiline ? `${Math.max(2, rows)*22+20}px` : '38px'}" :class="{code}" /></template>
<script>
export default {
    props:{modelValue:{default:''},theme:{type:String,default:'light'},disabled:Boolean,multiline:Boolean,code:Boolean,rows:{type:Number,default:4},label:{type:String,default:'输入'},placeholder:{type:String,default:''}},emits:['update:modelValue'],
    computed:{value:{get(){return this.modelValue??''},set(v){this.$emit('update:modelValue',v)}}}
}
</script>
<style scoped>.code :deep(textarea),.code :deep(input){font-family:ui-monospace,SFMono-Regular,monospace;font-size:13px;line-height:1.6}</style>
