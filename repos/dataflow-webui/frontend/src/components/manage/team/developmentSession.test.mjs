import test from 'node:test'
import assert from 'node:assert/strict'
import { shouldAutoLogin, markLoggedOut, clearLoggedOut } from './developmentSession.js'
test('only explicit development mode auto-enters; logout survives reload', () => {
    const values = new Map()
    const storage = { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v), removeItem: k => values.delete(k) }
    assert.equal(shouldAutoLogin({}, storage), false)
    assert.equal(shouldAutoLogin({ development: 'true' }, storage), false)
    assert.equal(shouldAutoLogin({ development: true }, storage), true)
    markLoggedOut(storage)
    assert.equal(shouldAutoLogin({ development: true }, storage), false)
    clearLoggedOut(storage)
    assert.equal(shouldAutoLogin({ development: true }, storage), true)
})
