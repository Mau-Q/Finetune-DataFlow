import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const source=readFileSync(new URL('./index.vue',import.meta.url),'utf8')
const method=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end)).trim().replace(/,$/,'')
test('cancelling a page change preserves the page offset and the current editor',async()=>{
 const code=method('        async page(delta)','        async loadFileMetadata')
 let accepted=false,loads=0
 const page=new Function('confirmDiscard','writeWorkspaceState',`return ({${code}}).page`)(async()=>accepted,()=>{})
 const vm={sampleDirty:true,metadataDirty:false,offset:20,selected:{id:'draft'},action:fn=>fn(),async loadSelected(){loads++}}
 await page.call(vm,20);assert.equal(vm.offset,20);assert.equal(loads,0)
 accepted=true;await page.call(vm,20);assert.equal(vm.offset,40);assert.equal(loads,1)
})
test('file switching retains unsaved metadata on cancellation',async()=>{
 const code=method('        async selectSource(index)','        sampleEditingChanged')
 const select=new Function('confirmDiscard',`return ({${code}}).selectSource`)(async()=>false)
 const vm={metadataDirty:true,sourceIndex:0}
 await select.call(vm,1);assert.equal(vm.sourceIndex,0)
 vm.metadataDirty=false;await select.call(vm,1);assert.equal(vm.sourceIndex,1)
})
