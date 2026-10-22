<template><fv-combobox @keydown="navigate" v-model="selection" :options="items" :theme="theme" :disabled="disabled" :placeholder="placeholder" :aria-label="label" :border-radius="6" style="width:100%" /></template>
<script>
export default {
    props: {modelValue:{default:''},options:{type:Array,default:()=>[]},theme:{type:String,default:'light'},disabled:Boolean,placeholder:{type:String,default:'请选择'},label:{type:String,default:'选项'}},
    emits:['update:modelValue'],
    methods:{navigate(event){
        if(this.disabled || !['ArrowDown','ArrowUp','Home','End'].includes(event.key))return
        event.preventDefault();event.stopPropagation()
        const index=this.items.findIndex(o=>o.key===this.modelValue)
        const next=event.key==='Home'?0:event.key==='End'?this.items.length-1:Math.max(0,Math.min(this.items.length-1,index+(event.key==='ArrowDown'?1:-1)))
        if(this.items[next] && !Object.is(this.items[next].key,this.modelValue))this.$emit('update:modelValue',this.items[next].key)
    }},
    computed:{
        items(){return this.options.map(o=>typeof o==='object'?{key:o.value,text:o.label}:{key:o,text:String(o)})},
        selection:{get(){return this.items.find(o=>o.key===this.modelValue)||{key:this.modelValue??'',text:''}},set(o){const key=o?.key??'';if(!Object.is(key,this.modelValue??''))this.$emit('update:modelValue',key)}}
    }
}
</script>
