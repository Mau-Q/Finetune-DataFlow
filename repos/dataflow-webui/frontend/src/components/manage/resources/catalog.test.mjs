import test from 'node:test'
import assert from 'node:assert/strict'
import {
    matchesSource,
    usageCount,
    pipelineOptions,
    filterResources,
    variablesOf,
    timeLabel
} from './catalog.js'
const rows = [
    {
        name: 'Own',
        source: 'user',
        description: '',
        usages: ['文本 SFT'],
        purpose: '生成',
        operators: ['FormatStrPromptedGenerator'],
        references: [{ pipeline_id: 'used' }]
    },
    {
        name: 'Builtin',
        source: 'builtin',
        description: '',
        usages: ['图文 SFT'],
        purpose: '生成',
        operators: ['PromptedVQAGenerator'],
        references: []
    },
    {
        name: 'Schema',
        source: 'builtin',
        description: '',
        resource_kind: 'schema',
        usages: ['通用'],
        purpose: '模型输出',
        operators: [],
        references: []
    }
]
const pipelines = [
    {
        id: 'used',
        operators: ['FormatStrPromptedGenerator'],
        schema_operators: ['FormatStrPromptedGenerator']
    },
    { id: 'candidate', operators: ['FormatStrPromptedGenerator'], schema_operators: [] }
]
test('defaults to every own resource and keeps builtins in a separate tab', () => {
    assert.deepEqual(
        filterResources(rows, {}).map((r) => r.name),
        ['Own']
    )
    assert.equal(filterResources(rows, { source: 'builtin' }).length, 2)
})
test('saved references and operator compatibility are different filters', () => {
    assert.equal(filterResources(rows, { pipeline: 'candidate' }, pipelines).length, 0)
    assert.equal(
        filterResources(rows, { pipeline: 'candidate', relation: 'compatible' }, pipelines).length,
        1
    )
    assert.equal(
        filterResources(rows, { pipeline: 'missing', relation: 'compatible' }, pipelines).length,
        0
    )
    assert.equal(
        filterResources(
            rows,
            { source: 'builtin', pipeline: 'used', relation: 'compatible' },
            pipelines
        )[0].name,
        'Schema'
    )
})
test('search, usage and purpose filters combine without inventing applicability', () => {
    assert.equal(
        filterResources(rows, { search: 'formatstr', usage: '文本 SFT', purpose: '生成' }).length,
        1
    )
    assert.equal(filterResources(rows, { operator: 'PromptedVQAGenerator' }).length, 0)
    assert.equal(filterResources(rows, { source: 'builtin', usage: '图文 SFT' }).length, 1)
})
test('variables preserve JSON literals and escapes, invalid times remain unknown', () => {
    assert.deepEqual(variablesOf('{{literal}} {q} {q} {"a":1} {input}'), ['q', 'input'])
    assert.equal(timeLabel(null), '未记录')
    assert.equal(timeLabel('invalid'), '未记录')
})

test('my dropdown contains two SFT families; builtin dropdown contains only shipped presets', () => {
    const options = [
        { id: 'preset', source: 'builtin', origin: 'preset', operators: ['Native'] },
        {
            id: 'custom',
            source: 'user',
            origin: 'custom',
            family: 'text-sft',
            operators: ['Generate']
        },
        {
            id: 'history',
            source: 'user',
            origin: 'custom',
            family: 'text-sft',
            operators: ['Evaluate']
        },
        {
            id: 'multimodal',
            source: 'user',
            origin: 'custom',
            family: 'image-sft',
            operators: ['VQA']
        },
        { id: 'template', source: 'builtin', origin: 'platform_template', family: 'text-sft' }
    ]
    const own = pipelineOptions(options, 'user')
    assert.deepEqual(
        own.map((p) => p.name),
        ['文本 SFT', '图像 SFT']
    )
    assert.deepEqual(own[0].member_ids, ['custom', 'history'])
    assert.deepEqual(own[0].operators, ['Generate', 'Evaluate'])
    assert.deepEqual(
        pipelineOptions(options, 'builtin').map((p) => p.id),
        ['preset']
    )
    const resource = { ...rows[0], references: [{ pipeline_id: 'history' }] }
    assert.equal(filterResources([resource], { pipeline: 'family:text-sft' }, own).length, 1)
    assert.equal(filterResources([resource], { pipeline: 'family:image-sft' }, own).length, 0)
})

test('my resources include used builtins while keeping ownership and unique flow counts', () => {
    const used = {
        ...rows[1],
        personal: true,
        references: [
            { pipeline_id: 'custom', pipeline_source: 'user' },
            { pipeline_id: 'custom', pipeline_source: 'user' },
            { pipeline_id: 'preset', pipeline_source: 'builtin' }
        ]
    }
    assert.deepEqual(
        filterResources([...rows, used], {}).map((r) => r.name),
        ['Own', 'Builtin']
    )
    assert.equal(usageCount(used), 1)
    assert.equal(matchesSource(used, 'user'), true)
    assert.equal(matchesSource(used, 'builtin'), true)
    assert.equal(used.source, 'builtin')
    assert.equal(filterResources([used], { pipeline: 'unreferenced' }).length, 0)
    assert.equal(filterResources([used], { pipeline: 'custom' }).length, 1)
})
