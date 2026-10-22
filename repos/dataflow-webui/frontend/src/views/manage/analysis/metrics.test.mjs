import test from 'node:test'
import assert from 'node:assert/strict'
import {canonicalStatus,durationMs,averageDuration,terminalSuccessRate} from './metrics.js'
test('completed and queued canonical status remain compatible with legacy records',()=>{
 assert.equal(canonicalStatus('success'),'completed'); assert.equal(canonicalStatus('pending'),'queued')
 assert.equal(terminalSuccessRate({completed:21,failed:5,cancelled:2,running:100}),75)
 assert.equal(terminalSuccessRate({success:2,failed:1,cancelled:1}),50)
 assert.equal(terminalSuccessRate({running:2}),0)
})
test('timing ignores missing, reversed and invalid timestamps instead of averaging zeros',()=>{
 const task={started_at:'2026-01-01T00:00:00Z',completed_at:'2026-01-01T00:00:02Z'}
 assert.equal(durationMs(task),2000)
 assert.equal(averageDuration([task,{}, {...task,completed_at:'bad'}]),'2.00s')
 assert.equal(durationMs({...task,completed_at:'2025-01-01'}),null)
 assert.equal(averageDuration([{}]),'暂无数据')
})
