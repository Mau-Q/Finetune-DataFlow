import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const source=readFileSync(new URL('./unsaved.js',import.meta.url),'utf8')
const body=source.slice(source.indexOf('export function useUnsavedChanges')).replace('export function','function')
function harness(answers){
 const hooks={}, events={}, vm={dirty:true}, listeners={}
 let guard,discarded=0,removed=0,prompts=0
 vm.$router={beforeEach(fn){guard=fn;return ()=>removed++}}
 const create=new Function('getCurrentInstance','onMounted','onBeforeUnmount','onActivated','onDeactivated','confirmDiscard','window',body+';return useUnsavedChanges')
 const use=create(()=>({proxy:vm}),fn=>hooks.mount=fn,fn=>hooks.unmount=fn,fn=>hooks.activate=fn,fn=>hooks.deactivate=fn,async()=>{prompts++;return answers.shift()},{addEventListener:(key,fn)=>listeners[key]=fn,removeEventListener:key=>delete listeners[key]})
 use(value=>value.dirty,()=>{discarded++;vm.dirty=false});hooks.mount()
 return {vm,hooks,listeners,run:()=>guard(),get discarded(){return discarded},get removed(){return removed},get prompts(){return prompts}}
}
test('navigation cancellation retains edits and confirmation discards once',async()=>{
 const h=harness([false,true]);assert.equal(await h.run(),false);assert.equal(h.vm.dirty,true);assert.equal(h.discarded,0)
 assert.equal(await h.run(),true);assert.equal(h.discarded,1);assert.equal(await h.run(),true);assert.equal(h.prompts,2)
})
test('inactive cached editors do not block navigation; unload and unmount clean up',async()=>{
 const h=harness([false]);let prevented=false
 const event={preventDefault(){prevented=true}};h.listeners.beforeunload(event);assert.equal(prevented,true);assert.equal(event.returnValue,'')
 h.hooks.deactivate();assert.equal(await h.run(),true);assert.equal(h.prompts,0)
 h.hooks.activate();assert.equal(await h.run(),false)
 h.hooks.unmount();assert.equal(h.removed,1);assert.equal(h.listeners.beforeunload,undefined)
})
