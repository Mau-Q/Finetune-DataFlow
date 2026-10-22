/* global globalThis */
import test from 'node:test'
import assert from 'node:assert/strict'
import {publishChange,subscribeChanges} from './changes.js'
test('same-window mutations, remote-tab storage events, invalid events and unsubscribe',()=>{
    globalThis.window=new EventTarget()
    let saved
    globalThis.localStorage={setItem:(key,value)=>{saved={key,value}}}
    const received=[]
    const stop=subscribeChanges(change=>received.push(change))
    publishChange('datasets','ds_new')
    assert.equal(received.length,1)
    assert.equal(received[0].id,'ds_new')
    function remote(key,newValue){const event=new Event('storage');Object.assign(event,{key,newValue});window.dispatchEvent(event)}
    remote(saved.key,JSON.stringify({topic:'resources',id:'schema_1'}))
    remote(saved.key,'broken json')
    remote('unrelated',saved.value)
    assert.equal(received.length,2)
    assert.equal(received[1].id,'schema_1')
    stop();publishChange('datasets','ignored');remote(saved.key,saved.value)
    assert.equal(received.length,2)
})
test('blocked browser storage still delivers local refresh',()=>{
    globalThis.window=new EventTarget()
    globalThis.localStorage={setItem:()=>{throw new Error('storage disabled')}}
    const received=[];const stop=subscribeChanges(change=>received.push(change))
    publishChange('resources','prompt_1');assert.equal(received[0].id,'prompt_1');stop()
})
