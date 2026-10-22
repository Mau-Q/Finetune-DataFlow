import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRenderer, h, reactive, nextTick} from 'vue'

const source=readFileSync(new URL('./NativeSelect.vue',import.meta.url),'utf8')
const options=new Function(source.match(/<script>([\s\S]*?)<\/script>/)[1].replace('export default','return'))()
// Fluent echoes a new model object through modelValue -> thisValue -> update:modelValue.
// This stub retains that watcher contract without requiring a browser DOM.
const FluentEcho={props:['modelValue','options'],emits:['update:modelValue'],watch:{modelValue(value){this.$emit('update:modelValue',value)}},render(){return h('select')}}
const Select={...options,render(){return h(FluentEcho,{modelValue:this.selection,options:this.items,'onUpdate:modelValue':value=>{this.selection=value}})}}
const renderer=createRenderer({
 createElement:tag=>({tag,children:[]}),createText:text=>({text}),createComment:()=>({}),
 setText(){},setElementText(){},patchProp(){},parentNode(){return null},nextSibling(){return null},
 insert(node,parent){parent.children.push(node)},remove(){}
})

test('refreshing option objects cannot echo the unchanged key and repeatedly reset previews',async()=>{
 const state=reactive({value:'',rows:[],updates:0,preview:[]})
 const Parent={render(){void state.preview.length;return h(Select,{modelValue:state.value,options:state.rows.map(row=>({...row})),
 'onUpdate:modelValue':value=>{state.value=value;state.updates++;if(state.updates<=12)state.preview=[]}})}}
 const app=renderer.createApp(Parent);app.mount({children:[]})
 state.rows=[{value:'draft',label:'Generated dataset'}];await nextTick()
 assert.equal(state.updates,0,'option hydration must not be treated as a dataset selection')
 state.value='draft';await nextTick();assert.equal(state.updates,0,'parent-driven selection must not echo back')
 app.unmount()
})

test('select emits one actual change and ignores same-key echoes and boundary navigation',()=>{
 const events=[], vm={modelValue:'a',$emit:(...args)=>events.push(args)}
 options.computed.selection.set.call(vm,{key:'a',text:'A refreshed'})
 assert.equal(events.length,0)
 options.computed.selection.set.call(vm,{key:'b',text:'B'})
 assert.deepEqual(events,[['update:modelValue','b']])
})
