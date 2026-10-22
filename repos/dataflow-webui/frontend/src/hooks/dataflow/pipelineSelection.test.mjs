import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {PLATFORM_PIPELINES} from './platformEntries.js'
const source=readFileSync(new URL('../../components/manage/mainFlow/pipeline/index.vue',import.meta.url),'utf8')
const component=new Function('mapState','mapActions','useAppConfig','useDataflow','useTheme','timeRounder','pipelinePanel','execLabel','pipelineIcon','PLATFORM_PIPELINES','usePipelineOperation',
 `return (${source.split('export default ')[1].split('</script>')[0]})`)(()=>({}),()=>({}),null,null,null,null,null,null,null,PLATFORM_PIPELINES,()=>({async renderPipeline(){}}))
const custom={id:'saved',name:'My SFT',tags:[],config:{operators:[]}},template={id:'template',name:'SFT Template',tags:['template'],config:{operators:[]}}
function state(mode='custom') {return {pipelines:[custom,template],choosenPivot:{key:mode},searchText:'',...component.methods}}
test('custom tab contains saved pipelines and excludes presets and templates',()=>{
 const s=state();assert.deepEqual(component.computed.filteredPipelines.call(s).map(p=>p.id),['saved'])
 s.searchText='no match';assert.equal(component.computed.filteredPipelines.call(s)[0].show,false)
})
test('templates and preset workflows have separate tabs',()=>{
 assert.deepEqual(component.computed.filteredPipelines.call(state('template')).map(p=>p.id),['template'])
 assert.deepEqual(component.computed.filteredPipelines.call(state('workflow')).map(p=>p.id),PLATFORM_PIPELINES.map(p=>p.id))
})
test('saved selection emits its identity after rendering and restores loading',async()=>{
 const s={...state(),thisLoading:true,$route:{query:{}},beforeChange:async()=>true,events:[],$emit(...event){this.events.push(event)}}
 await s.selectPipeline(custom);assert.equal(s.thisPipeline.id,'saved');assert(s.thisLoading)
 assert.deepEqual(s.events.find(e=>e[0]==='select-pipeline'),['select-pipeline',custom])
})
const page=readFileSync(new URL('../../views/manage/dataflow/index.vue',import.meta.url),'utf8')
const save=new Function(`return ({${page.slice(page.indexOf('        async handleSaveClick()'),page.indexOf('        async savePipeline()'))}})`)()
const selected=new Function(`return ({${page.slice(page.indexOf('        async selectPipelineCallback('),page.indexOf('        async selectExecutionPipeline('))}})`)()
test('selection callback binds existing ID even before v-model watcher runs',async()=>{
 const s={...selected,currentPipeline:null,executionInfo:{task_id:'old'},show:{pipeline:true},clearExecution(){},async $nextTick(){},async autoLayoutPipeline(){},markCanvasSaved(){}}
 await s.selectPipelineCallback(custom);assert.equal(s.currentPipeline.id,'saved');assert.equal(s.executionInfo.task_id,null)
 // Recover calls the same callback without replacing the saved identity.
 await s.selectPipelineCallback();assert.equal(s.currentPipeline.id,'saved')
})
test('Save and Run update an existing custom pipeline without opening Create',async()=>{
 const s={...save,currentPipeline:custom,show:{pipelinePanel:false},updates:[],async savePipeline(){this.updates.push(this.currentPipeline.id);return true}}
 assert(await s.handleSaveClick());assert.deepEqual(s.updates,['saved']);assert(!s.show.pipelinePanel)
 const methods=page.slice(page.indexOf('        async openRunConfirm()'),page.indexOf('        showExecDetails('))
 Object.assign(s,new Function(`return ({${methods}})`)(),{lock:{running:true},runPreparing:false,pendingRun:false})
 s.preflightIssues=[];s.inspectPreflight=async()=>{};await s.openRunConfirm();assert(s.show.runConfirm);assert(!s.show.pipelinePanel);assert.deepEqual(s.updates,['saved','saved'])
})
test('unsaved flows and templates still request a named copy',async()=>{
 for(const currentPipeline of [null,{id:null},template]){
 const s={...save,currentPipeline,show:{pipelinePanel:false},savePipeline(){throw Error('must not overwrite template')}}
 assert.equal(await s.handleSaveClick(),false);assert(s.show.pipelinePanel)
 }
})

test('existing custom Save calls update API with the same ID and preserves execution options',async()=>{
 const methods=page.slice(page.indexOf('        async savePipeline()'),page.indexOf('        async addPipeline('))
 const db={position:{x:1,y:2},data:{pipelineRole:'input'}}
 const saveMethods=new Function('useVueFlow',`return ({${methods}})`)(()=>({findNode:()=>db}))
 const calls=[],options={training_output:true}
 const s={...saveMethods,currentPipeline:{...custom,config:{file_path:'flow.py',execution_options:options}},nodes:[],sourceDatabase:{id:'dataset'},executionInfo:{},sortPipeline:()=>[],local:x=>x,getPipelines(){},markCanvasSaved(){},$barWarning(){},$api:{pipelines:{async update_pipeline(...args){calls.push(args);return {code:200}},create_pipeline(){throw Error('must not create')}}}}
 assert(await s.savePipeline());assert.equal(calls.length,1);assert.equal(calls[0][0],'saved');assert.equal(calls[0][1].config.execution_options,options)
})

test('execution selection and recovery release loading after render rejection', async()=>{
 const methods=page.slice(page.indexOf('        async selectExecutionPipeline('),page.indexOf('        async handleWatchExecution('))
 const selectedMethods=new Function('usePipelineOperation',`return ({${methods}})`)(()=>({async renderPipeline(){throw Error('fixture render failed')}}))
 for(const method of ['selectExecutionPipeline','recoverPipeline']) {
  const s={...selectedMethods,lock:{loading:true},currentPipeline:custom,async confirmCanvasChange(){return true}}
  await assert.rejects(s[method]({}), /fixture render failed/)
  assert.equal(s.lock.loading,true)
 }
})
