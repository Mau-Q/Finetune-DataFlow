import test from 'node:test'
import assert from 'node:assert/strict'
import { parseAdvancedPlan } from './planEditing.mjs'
const defaults = () => ({
    name: 'draft',
    data: [],
    strategy: { family: 'static', params: {} },
    advanced: {}
})

test('advanced roundtrip preserves custom fields and component-specific nested configuration', () => {
    const value = {
        ...defaults(),
        strategy: {
            family: 'lego',
            params: {
                stages: [{ family: 'selector', component: 'custom', params: { nested: [1, 2] } }]
            }
        },
        research_note: 'keep me',
        advanced: { cutoff_len: 128 }
    }
    assert.deepEqual(parseAdvancedPlan(JSON.stringify(value), defaults()), value)
})
test('malformed editor structures are rejected before replacing the existing form', () => {
    const baseline = defaults(),
        serialized = JSON.stringify(baseline)
    for (const patch of [
        { strategy: null },
        { strategy: [] },
        { strategy: { family: 'selection', params: null } },
        { data: [null] },
        { data: {} },
        { strategy: { family: 'lego', params: { stages: [null] } } }
    ]) {
        assert.throws(() => parseAdvancedPlan(JSON.stringify({ ...baseline, ...patch }), baseline))
        assert.equal(JSON.stringify(baseline), serialized)
    }
})
test('invalid JSON stays an editor error and does not become a partial plan', () => {
    assert.throws(() => parseAdvancedPlan('{"strategy":', defaults()))
    assert.throws(() => parseAdvancedPlan('[]', defaults()))
})
