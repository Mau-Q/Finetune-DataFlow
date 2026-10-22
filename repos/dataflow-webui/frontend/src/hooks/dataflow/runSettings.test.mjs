import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const page=readFileSync(new URL('../../views/manage/dataflow/index.vue',import.meta.url),'utf8')
const methods=page.slice(page.indexOf('        async openRunConfirm()'),page.indexOf('        showExecDetails('))
const run=new Function(`return ({${methods}})`)()
function state(saved=true) {return {...run,preflightIssues:[],async inspectPreflight(){this.showPreflight=true},focusIssue(){},show:{runConfirm:false,pipelinePanel:false},lock:{running:true},runPreparing:false,pendingRun:false,isMM:false,saves:0,submits:[],async handleSaveClick(){this.saves++;if(!saved)this.show.pipelinePanel=true;return saved},async executePipeline(o){this.submits.push(o)},$barWarning(){},local:x=>x}}
test('one Run confirmation saves once and submits chosen target once',async()=>{
 const s=state();await s.openRunConfirm();await s.openRunConfirm();assert.equal(s.saves,1);assert(s.show.runConfirm)
 const o={output_root:'/results',collection_target:{mode:'append',draft_id:'chosen'}}
 await s.handleRunClick(o);await s.handleRunClick(o);assert.deepEqual(s.submits,[o]);assert.equal(s.saves,1)
})
test('first template save continues without another Run click',async()=>{
 const s=state(false);await s.openRunConfirm();assert(s.pendingRun);assert(!s.show.runConfirm)
 s.resumeRunAfterSave();assert(s.show.runConfirm);assert(!s.pendingRun)
 await s.handleRunClick({});assert.equal(s.submits.length,1);assert.equal(s.saves,1)
})
test('slow save ignores repeated clicks',async()=>{
 const s=state();let finish;s.handleSaveClick=()=>new Promise(r=>{finish=r})
 const first=s.openRunConfirm();await s.openRunConfirm();assert(s.runPreparing)
 finish(true);await first;assert(s.show.runConfirm);assert(!s.runPreparing)
})
test('failed save stops before directory confirmation and clears busy',async()=>{
 const s=state();s.handleSaveClick=async()=>{throw Error('save failed')}
 await s.openRunConfirm();assert(!s.show.runConfirm);assert(!s.runPreparing);assert(!s.submits.length)
})
test('submission failure permits retry',async()=>{
 const s=state();s.executePipeline=async()=>{throw Error('offline')};await s.handleRunClick({});assert(s.lock.running)
})
const src=readFileSync(new URL('../../components/manage/mainFlow/panels/runConfirmPanel.vue',import.meta.url),'utf8')
let prefs={},drafts=[]
const panel=new Function('axios','BasePanel',`return ({${src.split('export default {')[1].split('</script>')[0]})`)({get:async url=>({data:{success:true,data:url.includes('collection-target')?prefs:drafts}})}, {})
function panelState(){
 const s={...panel.data(),...panel.methods,modelValue:true,pipelineName:'Text DPO',contract:{modality:'text',training_type:'dpo'},events:[],async request(){return {output_root:'/results'}},$emit(...x){this.events.push(x)}}
 for(const [k,d] of Object.entries(panel.computed))Object.defineProperty(s,k,{get:()=>typeof d==='function'?d.call(s):d.get.call(s),set:v=>d.set?.call(s,v)})
 return s
}
test('compatible append is remembered and sent with one directory check',async()=>{
 drafts=[{id:'dpo',modality:'text',training_type:'dpo',name:'DPO'},{id:'sft',modality:'text',training_type:'sft'}];prefs={'text:dpo':{mode:'append',draft_id:'dpo'}}
 const s=panelState();await s.load();assert.equal(s.collectionMode,'append');assert.equal(s.draftId,'dpo');assert.equal(s.compatibleDrafts.length,1)
 let checks=0;s.request=async()=>{checks++;return {output_root:'/selected'}};await s.confirm();assert.equal(checks,1)
 assert.deepEqual(s.events.at(-1),['confirm',{output_root:'/selected',collection_target:{mode:'append',name:'',draft_id:'dpo'}}])
})
test('incompatible or missing remembered target falls back to new',async()=>{
 drafts=[{id:'sft',modality:'text',training_type:'sft'}];prefs={'text:dpo':{mode:'append',draft_id:'sft'}}
 const s=panelState();await s.load();assert.equal(s.collectionMode,'new');assert.equal(s.collectionName,'Text DPO')
 s.collectionName=' mine ';await s.confirm();assert.equal(s.events.at(-1)[1].collection_target.name,'mine')
})
test('blank name and missing append target cannot submit',async()=>{
 const s=panelState();s.collectionName=' ';await s.confirm();assert.equal(s.events.length,0)
 s.collectionMode='append';s.draftId='missing';await s.confirm();assert.equal(s.events.length,0)
})
test('new name persists on reopening',async()=>{
 drafts=[];prefs={'text:dpo':{mode:'new',name:'remembered'}};const s=panelState();await s.load();assert.equal(s.collectionName,'remembered')
})
const canvas=readFileSync(new URL('../../components/manage/mainFlow/index.vue',import.meta.url),'utf8')
const selection=canvas.slice(canvas.indexOf('const canvasFlow ='),canvas.indexOf('const isDragOver ='))
test('inspector follows live replacement and reopens same node',()=>{
 const ref=value=>({value}),computed=fn=>({get value(){return fn()}})
 const h=new Function('ref','computed','watch','props','emits','useVueFlow','onDeactivated',`${selection};return {thisNodes,selectedOperator,showInspector,inspectOperator,closeInspector,selectOperator}`)(ref,computed,()=>{},{nodes:[{id:'a',type:'operator-node',data:{name:'old'}}],edges:[]},()=>{},()=>({findNode:()=>null}),()=>{})
 h.inspectOperator('a');assert(h.showInspector.value)
 h.thisNodes.value=[{id:'a',type:'operator-node',data:{name:'current'}}];assert.equal(h.selectedOperator.value.data.name,'current')
 h.closeInspector();h.inspectOperator('a');assert(h.showInspector.value)
 h.selectOperator({node:{id:'db',type:'database-node'}});assert(!h.showInspector.value)
})

const nodeSource=readFileSync(new URL('../../components/manage/mainFlow/nodes/operatorNode/index.vue',import.meta.url),'utf8').replace(/\r\n/g, '\n')
const loader=nodeSource.slice(nodeSource.indexOf('let detailRequest ='),nodeSource.indexOf('watch(\n    () => dataflow.executionStep'))
const {reactive,ref,watch,nextTick}=await import('vue')
test('parameter loading updates cannot trigger an endless request loop',async()=>{
 const props=reactive({id:'node',data:{name:'Operator',flowId:'flow'}});let calls=0
 const api={operators:{async get_operator_detail_by_name(){calls++;return {code:200,data:{parameter:{init:[{name:'a',value:'saved'}],run:[]}}}}}}
 const emits=(kind,info)=>{if(kind==='update-node-data')props.data={...props.data,...info.data}}
 const h=new Function('props','loading','emits','$api','paramsWrapper','watch',`${loader};return {getNodeDetail,inspect}`)(props,ref(false),emits,api,x=>x,watch)
 await h.getNodeDetail();await nextTick();await nextTick();assert.equal(calls,1);assert.equal(props.data.operatorParams.init[0].value,'saved')
 props.data={...props.data,other:'changed'};await nextTick();assert.equal(calls,1)
})
test('parameter request failure is visible and another click retries',async()=>{
 const props=reactive({id:'node',data:{name:'Operator',flowId:'flow'}});let calls=0,opens=0
 const api={operators:{async get_operator_detail_by_name(){if(++calls===1)throw Error('offline');return {code:200,data:{parameter:{init:[],run:[]}}}}}}
 const emits=(kind,info)=>{if(kind==='update-node-data')props.data={...props.data,...info.data};else if(kind==='inspect-node')opens++}
 const h=new Function('props','loading','emits','$api','paramsWrapper','watch',`${loader};return {getNodeDetail,inspect}`)(props,ref(false),emits,api,x=>x,watch)
 await h.getNodeDetail();assert.equal(props.data.parameterError,'offline');h.inspect();await nextTick();await nextTick()
 assert.equal(opens,1);assert.equal(calls,2);assert.equal(props.data.parameterError,'');assert(props.data.operatorParams)
})

test('explicit inspector uses live graph even while v-model nodes lag behind',()=>{
 const ref=value=>({value}),computed=fn=>({get value(){return fn()}})
 const live={id:'live',type:'operator-node',data:{name:'live current data'}}
 const h=new Function('ref','computed','watch','props','emits','useVueFlow','onDeactivated',`${selection};return {selectedOperator,showInspector,inspectOperator}`)(ref,computed,()=>{},{id:'flow',nodes:[],edges:[]},()=>{},()=>({findNode:id=>id==='live'?live:null}),()=>{})
 h.inspectOperator('live');assert(h.showInspector.value);assert.equal(h.selectedOperator.value,live)
})

test('primary pointer release opens details independently of a suppressed click',()=>{
 const props={id:'node',data:{operatorParams:{init:[],run:[]}}};let opens=0
 const h=new Function('props','loading','emits','$api','paramsWrapper','watch',`${loader};return {inspectPointer}`)(props,ref(false),(kind)=>{if(kind==='inspect-node')opens++},{},x=>x,()=>{})
 h.inspectPointer({button:0});assert.equal(opens,1)
 h.inspectPointer({button:2});assert.equal(opens,1)
})

test('repeated detail activation shares the pending request and keeps the inspector open', async()=>{
 const props=reactive({id:'node',data:{name:'Operator',flowId:'flow'}})
 let calls=0,opens=0,finish
 const api={operators:{get_operator_detail_by_name(){calls++;return new Promise(resolve=>{finish=resolve})}}}
 const emits=(kind,info)=>{if(kind==='update-node-data')props.data={...props.data,...info.data};else if(kind==='inspect-node')opens++}
 const h=new Function('props','loading','emits','$api','paramsWrapper','watch',`${loader};return {getNodeDetail,inspect}`)(props,ref(false),emits,api,x=>x,()=>{})
 const request=h.getNodeDetail()
 h.inspect();h.inspect()
 assert.equal(calls,1);assert.equal(opens,2)
 finish({code:200,data:{parameter:{init:[],run:[]}}})
 await request
 assert.equal(props.data.parameterLoading,false)
 assert(props.data.operatorParams)
})

test('a changed operator starts a new request and ignores the old response', async()=>{
 const props=reactive({id:'node',data:{name:'Old',flowId:'flow'}})
 const finishes={}
 const api={operators:{get_operator_detail_by_name(name){return new Promise(resolve=>{finishes[name]=resolve})}}}
 const emits=(kind,info)=>{if(kind==='update-node-data')props.data={...props.data,...info.data}}
 const h=new Function('props','loading','emits','$api','paramsWrapper','watch',`${loader};return {getNodeDetail}`)(props,ref(false),emits,api,x=>x,()=>{})
 const old=h.getNodeDetail();props.data.name='New';const current=h.getNodeDetail()
 finishes.New({code:200,data:{parameter:{init:[{name:'new'}],run:[]}}});await current
 finishes.Old({code:200,data:{parameter:{init:[{name:'old'}],run:[]}}});await old
 assert.equal(props.data.operatorParams.init[0].name,'new')
 assert.equal(props.data.parameterLoading,false)
})

test('canvas fits unbound templates once, waits for complete nodes, and supports bound input', async()=>{
 const method=page.slice(page.indexOf('        async fitPlatformWhenReady()'),page.indexOf('        async platformRequest(')).trim().replace(/,$/,'')
 for(const bound of [false,true]){
  let fits=0
  const nodes={value:[{id:'op-1'}]}
  const flow={nodes,findNode:()=>bound?{id:'db-node'}:null,fitView(){fits++}}
  const fit=new Function('useVueFlow',`return ({${method}}).fitPlatformWhenReady`)(()=>flow)
  const ctx={flowId:'flow',currentPipeline:{config:{operators:[{},{}]}},isMM:false,$route:{fullPath:'/m'},$nextTick:async()=>{},platformFitKey:'',markCanvasSaved(){this.canvasBaseline='saved'}}
  await fit.call(ctx);assert.equal(fits,0)
  nodes.value=[{id:'op-1'},{id:'op-2'},...(bound?[{id:'db-node'}]:[])]
  await fit.call(ctx);assert.equal(fits,1)
  await fit.call(ctx);assert.equal(fits,1)
 }
})


test('automatic graph initialization is clean, actual edits are guarded, and reverting clears dirty state',()=>{
 const method=page.slice(page.indexOf('        canvasDirty(){'),page.indexOf('        runCollectionContract()')).trim().replace(/,$/,'')
 const dirty=new Function(`return ({${method}}).canvasDirty`)()
 const vm={canvasEdited:false,canvasBaseline:'initial',canvasFingerprint:'normalized metadata'}
 assert.equal(dirty.call(vm),false)
 vm.canvasEdited=true;assert.equal(dirty.call(vm),true)
 vm.canvasFingerprint='initial';assert.equal(dirty.call(vm),false)
})

test('preflight problems block save and submission and focus the affected field',async()=>{
 const s=state();const issue={nodeId:'op',message:'缺少模型服务'};s.preflightIssues=[issue];s.focusIssue=value=>{s.focused=value};await s.openRunConfirm();assert.equal(s.saves,0);assert.equal(s.submits.length,0);assert.equal(s.focused,issue);assert(s.showPreflight)
})
