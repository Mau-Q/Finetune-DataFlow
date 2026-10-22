import test from 'node:test'
import assert from 'node:assert/strict'
import {nativeMMGraph,readNativeMM} from './nativeMM.js'
const config=()=>({material_ids:['image-id'],draft_id:'draft-id',max_workers:2,timeout:1800,steps:[
 {id:'question',kind:'mm:PromptedVQAGenerator',inputs:{image:'image'},output:'question',resource_ref:'builtin:mm-question-v1',bindings:{},x:20,y:30},
 {id:'answer',kind:'mm:PromptedVQAGenerator',inputs:{image:'image',question:'question'},output:'answer',resource_ref:'builtin:mm-answer-v1',bindings:{question:'question'},x:310,y:30},
 {id:'validate',kind:'platform:validate',inputs:{question:'question',answer:'answer'},output:'validated',resource_ref:'builtin:mm-qa-schema-v1',bindings:{},x:600,y:30},
 {id:'format',kind:'platform:messages',inputs:{image:'image',question:'question',answer:'answer'},output:'messages',resource_ref:'builtin:mm-messages-v1',bindings:{},x:890,y:30}]})
test('native MM round trip preserves config and reuses original node/edge types',()=>{
 const original=config(),graph=nativeMMGraph(original,'native',{})
 assert.equal(graph.nodes[0].type,'database-node')
 assert(graph.nodes.slice(1).every(n=>n.type==='operator-node'&&n.data.externalTemplate))
 assert(graph.edges.every(e=>e.type==='base-edge'))
 assert.deepEqual(readNativeMM(original,graph.nodes),original)
})
test('native parameter edits and dragging serialize without mutating saved source',()=>{
 const original=config(),before=structuredClone(original),graph=nativeMMGraph(original,'native',{})
 const answer=graph.nodes.find(n=>n.data.mmStepId==='answer')
 answer.data.operatorParams.init[0].value='user_prompt:alternate'
 answer.data.operatorParams.run.find(p=>p.name==='binding_question').value='question'
 answer.position.x+=45
 const result=readNativeMM(original,graph.nodes)
 assert.equal(result.steps[1].resource_ref,'user_prompt:alternate')
 assert.equal(result.steps[1].x,355)
 assert.deepEqual(original,before)
 assert.equal(result.draft_id,'draft-id')
 assert.deepEqual(result.material_ids,['image-id'])
})
test('missing steps and out-of-range layouts cannot silently save',()=>{
 const c=config(),g=nativeMMGraph(c,'native',{})
 assert.throws(()=>readNativeMM(c,g.nodes.slice(0,-1)),/缺少步骤/)
 assert.throws(()=>readNativeMM(c,[...g.nodes,{id:'core',type:'operator-node',data:{}}]),/额外节点/)
 g.nodes[1].position.x=-500
 assert.throws(()=>readNativeMM(c,g.nodes),/超出/)
})
test('switching MM templates serializes the current binding set, including additions and removals',()=>{
 const original=config(),graph=nativeMMGraph(original,'native',{})
 const question=graph.nodes.find(n=>n.data.mmStepId==='question')
 question.data.operatorParams.init[0].value='user_prompt:with-image'
 question.data.operatorParams.run.push({name:'binding_image',value:'image',show:true})
 assert.deepEqual(readNativeMM(original,graph.nodes).steps[0].bindings,{image:'image'})
 const answer=graph.nodes.find(n=>n.data.mmStepId==='answer')
 answer.data.operatorParams.run=answer.data.operatorParams.run.filter(p=>p.name!=='binding_question')
 assert.deepEqual(readNativeMM(original,graph.nodes).steps[1].bindings,{})
 assert.deepEqual(original.steps[1].bindings,{question:'question'})
})
