import test from 'node:test'
import assert from 'node:assert/strict'
import {filtersFromQuery,queryForFilters} from './resourceQuery.js'
test('clearing URL filters resets compatibility, pipeline and operator together',()=>{
    const old=filtersFromQuery({pipeline:'family:text-sft',operator:'FormatStrPromptedGenerator',relation:'compatible'})
    assert.equal(old.relation,'compatible')
    assert.deepEqual(filtersFromQuery({}),{source:'user',search:'',usage:'',purpose:'',pipeline:'',operator:'',relation:'referenced'})
})
test('round-trip keeps resource detail and every active filter without reviving cleared values',()=>{
    const filters={source:'builtin',search:'问答',usage:'文本 SFT',purpose:'生成',pipeline:'pipeline:used',operator:'Generator',relation:'compatible'}
    const query=queryForFilters({resource:'builtin_prompt:X'},filters)
    assert.equal(query.resource,'builtin_prompt:X')
    assert.deepEqual(filtersFromQuery(query),filters)
    const cleared=queryForFilters(query,filtersFromQuery({}))
    assert.deepEqual(cleared,{resource:'builtin_prompt:X'})
})
test('editing a personal copy drops builtin scope but keeps explicit filters and detail',()=>{
    const filters={...filtersFromQuery({source:'builtin',q:'answer',relation:'compatible'}),source:'user'}
    const query=queryForFilters({resource:'user_prompt:copy',source:'builtin'},filters)
    assert.equal(query.source,undefined)
    assert.equal(query.resource,'user_prompt:copy')
    assert.equal(query.q,'answer')
    assert.equal(query.relation,'compatible')
})
