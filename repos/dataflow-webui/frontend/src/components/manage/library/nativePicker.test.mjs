import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

test('local development uses the native picker while LAN uploads stay in the browser', async () => {
    const source = readFileSync(new URL('./SourceDatasetImport.vue', import.meta.url), 'utf8')
    const body = source.slice(source.indexOf('        async pick() {'), source.indexOf('        async submit() {')).trim().replace(/,$/, '')
    for (const [enabled, development, expectedNative] of [[true, true, true], [true, false, false], [false, false, true]]) {
        let native = 0, browser = 0
        const team = { enabled, development }
        const axios = { post: async () => { native++; return { data: { success: true, data: { cancelled: true } } } } }
        const method = new Function('team', 'axios', `return ({${body}}).pick`)(team, axios)
        const ctx = { $refs: { files: { click: () => browser++ } }, busy: false, choosing: false }
        await method.call(ctx)
        assert.equal(native, expectedNative ? 1 : 0)
        assert.equal(browser, expectedNative ? 0 : 1)
        assert.equal(ctx.choosing, false)
    }
})
