import test from 'node:test'
import assert from 'node:assert/strict'
import {executionProgress, elapsedLabel} from './executionProgress.js'
import {checkPipeline} from './preflight.js'
import {withoutCredentials} from './draftSnapshot.js'

test('step count is not presented as a fabricated task percentage',()=>{
 const view=executionProgress({status:'running',pipeline_config:{operators:[{name:'Slow'},{name:'Fast'}]},operators_detail:{Slow_0:{name:'Slow',index:0,status:'running'}}})
 assert.equal(view.completed,0);assert.equal(view.total,2);assert.equal(view.active.name,'Slow');assert.equal(view.steps[0].percentage,null);assert.equal(view.steps[1].status,'waiting')
 assert.equal(view.percentage,undefined)
})
test('reported step percentage is bounded and stale progress is hidden when finished',()=>{
 for(const value of [NaN,Infinity,'50',null]) assert.equal(executionProgress({operators_detail:{op:{name:'A',index:0,status:'running',progress_percentage:value}}}).steps[0].percentage,null)
 assert.equal(executionProgress({operators_detail:{op:{name:'A',index:0,status:'running',progress_percentage:120}}}).steps[0].percentage,100)
 assert.equal(executionProgress({operators_detail:{op:{name:'A',index:0,status:'completed',progress_percentage:50}}}).steps[0].percentage,null)
})
test('repeated operators keep separate indices; failed and unreported steps stay distinct',()=>{
 const view=executionProgress({status:'failed',pipeline_config:{operators:[{name:'Same'},{name:'Same'},{name:'Last'}]},operators_detail:{Same_0:{name:'Same',index:0,status:'completed'},Same_1:{name:'Same',index:1,status:'failed',error:'quota exceeded'}}})
 assert.equal(view.completed,1);assert.equal(view.error,'quota exceeded');assert.equal(view.steps[2].status,'skipped');assert.notEqual(view.steps[0].key,view.steps[1].key)
 assert.equal(executionProgress({status:'completed',pipeline_config:{operators:[{name:'A'}]}}).steps[0].status,'unknown')
})
test('elapsed timer handles missing timestamps and hour-long tasks',()=>{
 assert.equal(elapsedLabel(null,null),'尚未开始');assert.equal(elapsedLabel('invalid',null),'用时未知')
 assert.equal(elapsedLabel('2026-10-21T10:00:00Z','2026-10-21T11:01:02Z'),'1:01:02')
})
const db={id:'db',type:'database-node',data:{label:'Input'}}
const op={id:'op',type:'operator-node',data:{name:'Generator',label:'Generator',operatorParams:{init:[{name:'llm_serving',value:null}],run:[{name:'storage',required:true,value:null},{name:'input_key',required:true,value:''}]}}}
test('preflight locates missing serving, fields, input and disconnected operators',()=>{
 const issues=checkPipeline([db,op],[],{id:'source'})
 assert(issues.some(i=>i.kind==='graph'&&i.nodeId==='op'));assert(issues.some(i=>i.kind==='serving'));assert(issues.some(i=>i.message.includes('input_key')));assert(!issues.some(i=>i.message.includes('storage')))
 assert(checkPipeline([op],[],null).some(i=>i.kind==='input'))
})
test('preflight accepts false and zero values, optional null and legitimate connected flows',()=>{
 const node=structuredClone(op);node.data.operatorParams={init:[{name:'enabled',required:true,value:false},{name:'n',required:true,value:0},{name:'optional',required:false,value:null}],run:[]}
 assert.deepEqual(checkPipeline([db,node],[{source:'db',target:'op'}],{id:'source'}),[])
 assert(checkPipeline([db,node],[{source:'db',target:'op'},{source:'op',target:'db'}],{id:'source'}).some(i=>i.kind==='graph'))
})
test('draft snapshot removes credentials recursively without changing the live configuration',()=>{
 const live={params:[{name:'api_key',value:'secret-value',default_value:'also-secret'},{name:'input_key',value:'text'}],nested:{password:'hidden',temperature:0},api_key:'hidden',viewport:{zoom:0.8}}
 const saved=withoutCredentials(live)
 assert.equal(saved.params[0].value,null);assert.equal(saved.params[0].default_value,null);assert.equal(saved.params[1].value,'text');assert.equal(saved.nested.password,undefined);assert.equal(saved.nested.temperature,0)
 assert.equal(live.params[0].value,'secret-value')
})

test('native text controls display null without changing optional values or falsy defaults',async()=>{
 const {readFileSync}=await import('node:fs')
 const source=readFileSync(new URL('../../components/manage/mainFlow/nodes/operatorNode/valueInput/index.vue',import.meta.url),'utf8')
 const methods=source.slice(source.indexOf('        textValue: {'),source.indexOf('        ...mapState'))
 const model=new Function(`return ({${methods}}).textValue`)()
 for(const [value,text] of [[null,''],[undefined,''],[0,'0'],[false,'false']]){
  const state={thisValue:value};assert.equal(model.get.call(state),text);assert.equal(state.thisValue,value)
 }
 const state={thisValue:null};model.set.call(state,'text');assert.equal(state.thisValue,'text')
})

test('browser preferences and recovery snapshots remain scoped to account and project',async()=>{
 const {readFileSync}=await import('node:fs')
 const source=readFileSync(new URL('./workspaceState.js',import.meta.url),'utf8')
 const fn=source.slice(source.indexOf('export function workspaceKey'),source.indexOf('export function readWorkspaceState')).replace('export ','')
 const key=identity=>new Function('team',`return (${fn})`)(identity)('canvas')
 assert.notEqual(key({enabled:true,viewer:'alice',project:'one'}),key({enabled:true,viewer:'bob',project:'one'}))
 assert.notEqual(key({enabled:true,viewer:'alice',project:'one'}),key({enabled:true,viewer:'alice',project:'two'}))
 assert.notEqual(key({enabled:false}),key({enabled:true,viewer:'alice',project:'one'}))
})

test('an explicit empty filter survives refresh, while corrupt or unavailable storage has a fallback',async()=>{
 const {readFileSync}=await import('node:fs')
 const source=readFileSync(new URL('./workspaceState.js',import.meta.url),'utf8')
 const fn=source.slice(source.indexOf('export function readWorkspaceState'),source.indexOf('export { withoutCredentials')).replace('export ','')
 for(const value of ['',false,0]){
  const read=new Function('localStorage','workspaceKey',`return (${fn})`)({getItem:()=>JSON.stringify(value)},key=>key)
  assert.equal(read('filter','generated'),value)
 }
 for(const storage of [{getItem:()=>'{broken'}, {getItem(){throw Error('disabled')}}]){
  const read=new Function('localStorage','workspaceKey',`return (${fn})`)(storage,key=>key)
  assert.equal(read('filter','generated'),'generated')
 }
})
