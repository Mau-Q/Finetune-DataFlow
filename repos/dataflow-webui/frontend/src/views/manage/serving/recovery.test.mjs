import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
const source=readFileSync(new URL('./index.vue',import.meta.url),'utf8')
const method=source.slice(source.indexOf('        testServing(item) {'),source.indexOf('        delServing(item) {')).trim().replace(/,$/,'')
test('HTTP rejection releases the serving test lock and allows a subsequent retry',async()=>{
 const invoke=new Function(`return ({${method}}).testServing`)()
 let calls=0,warnings=0
 const vm={lock:{test:true},$barWarning(){warnings++},$api:{serving:{test_serving_instance(){calls++;return Promise.reject(new Error('offline'))}}}}
 invoke.call(vm,{id:'fake'});await new Promise(resolve=>setImmediate(resolve))
 assert.equal(vm.lock.test,true);assert.equal(warnings,1)
 invoke.call(vm,{id:'fake'});await new Promise(resolve=>setImmediate(resolve));assert.equal(calls,2)
})
