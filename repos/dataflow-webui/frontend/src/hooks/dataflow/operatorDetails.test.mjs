import test from 'node:test'
import assert from 'node:assert/strict'
import { createOperatorDetailLoader } from './operatorDetails.js'

test('repeated nodes share one request but have independent parameter objects', async () => {
    let calls = 0
    const load = createOperatorDetailLoader(async (name) => {
        calls++
        return { code: 200, data: { name, parameter: { init: [{ value: 'default' }] } } }
    })
    const nodes = await Promise.all(Array.from({ length: 20 }, () => load('Generator')))
    assert.equal(calls, 1)
    nodes[0].data.parameter.init[0].value = 'edited'
    assert.equal(nodes[1].data.parameter.init[0].value, 'default')
    await load('Filter')
    assert.equal(calls, 2)
})

test('failed metadata requests can retry and a new graph load gets fresh metadata', async () => {
    let calls = 0
    const fetchDetail = async () => {
        if (++calls === 1) throw new Error('offline')
        return { code: 200, data: { version: calls } }
    }
    const load = createOperatorDetailLoader(fetchDetail)
    await assert.rejects(load('Generator'), /offline/)
    assert.equal((await load('Generator')).data.version, 2)
    const nextGraph = createOperatorDetailLoader(fetchDetail)
    assert.equal((await nextGraph('Generator')).data.version, 3)
})

test('unsuccessful API envelopes are not cached', async () => {
    let calls = 0
    const load = createOperatorDetailLoader(async () => ({ code: ++calls === 1 ? 500 : 200 }))
    assert.equal((await load('Generator')).code, 500)
    assert.equal((await load('Generator')).code, 200)
})
