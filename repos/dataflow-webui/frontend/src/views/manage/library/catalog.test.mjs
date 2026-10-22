import test from 'node:test'
import assert from 'node:assert/strict'
import { sourceType, sourceCount, recentFirst, formatTime, recordTime, releaseLabel } from './catalog.js'

test('catalog classifies actual materials separately from their JSONL manifest', () => {
    assert.equal(sourceType({type:'jsonl',content_type:'pdf'}), 'PDF')
    assert.equal(sourceCount({type:'jsonl',content_type:'pdf',file_count:13,num_samples:13}), '13 个文件')
    assert.equal(sourceType({type:'jsonl',content_type:'pdf_image'}), '混合')
    assert.equal(sourceCount({type:'jsonl',content_type:'image',file_count:8}), '8 张图片')
    assert.equal(sourceType({type:'jsonl'}), '结构化数据')
    assert.equal(sourceCount({type:'csv',num_samples:12000}), '12,000 条记录')
    assert.equal(sourceCount({type:'txt',num_samples:400}), '1 个文件')
    assert.equal(sourceType({type:'unknown'}), '未识别')
})
test('recent updates sort ahead of creation dates without mutating input or inventing times', () => {
    const rows = [{id:'old',added_at:'2026-01-01'}, {id:'updated',created_at:'2025-01-01',updated_at:'2026-10-19T01:00:00Z'}, {id:'missing'}, {id:'created',created_at:'2026-10-18T01:00:00Z'}]
    assert.deepEqual(recentFirst(rows).map(r=>r.id), ['updated','created','old','missing'])
    assert.equal(rows[0].id, 'old')
    assert.equal(recordTime(rows[0]), '2026-01-01')
    assert.equal(formatTime('invalid'), '未记录')
    assert.equal(formatTime(null), '未记录')
    assert.match(formatTime('2026-10-19T10:05:06+08:00', true), /^2026-10-19 \d\d:05:06$/)
})
test('latest release remains distinct from the editable draft status', () => {
    assert.equal(releaseLabel({status:'draft',latest_release_version:3}), 'v3')
    assert.equal(releaseLabel({status:'draft',latest_release_version:null}), '未发布')
})

test('folder scanning includes nested supported files and reports skipped files', async () => {
    const { scanFolder } = await import('./catalog.js')
    const file = (path) => ({name:path.split('/').pop(),webkitRelativePath:path})
    const result = scanFolder(['data/a.pdf','data/nested/a.txt','data/.DS_Store','data/tool.exe','data/.git/file.csv','data/a.png'].map(file))
    assert.equal(result.type, '混合')
    assert.equal(result.accepted.length, 3)
    assert.deepEqual(result.skipped, ['data/.DS_Store','data/tool.exe','data/.git/file.csv'])
    assert.equal(scanFolder(['data/a.csv','data/b.jsonl'].map(file)).type, '结构化数据')
    assert.equal(scanFolder(['data/a.txt','data/b.md'].map(file)).type, '文本')
    assert.equal(scanFolder([file('data/a.exe')]).type, '未识别')
})

test('drop accepts both files and directories without a mode switch and reads every directory batch', async () => {
    const { droppedSelection, scanFolder } = await import('./catalog.js')
    const leaf = name => ({name,isFile:true,file:resolve=>resolve({name,size:10})})
    const folder = {name:'folder',isDirectory:true,createReader:()=>{
        const batches = [[leaf('a.pdf')],[leaf('b.csv')],[]]
        return {readEntries:resolve=>resolve(batches.shift())}
    }}
    const result = await droppedSelection([{webkitGetAsEntry:()=>folder}, {webkitGetAsEntry:()=>leaf('note.txt')}])
    assert.equal(result.hasDirectory, true)
    assert.deepEqual(result.files.map(f=>f.webkitRelativePath), ['folder/a.pdf','folder/b.csv','note.txt'])
    assert.equal(scanFolder(result.files).type, '混合')
    const plain = await droppedSelection([{getAsFile:()=>({name:'a.txt',size:3})}])
    assert.equal(plain.hasDirectory, false)
    assert.equal(plain.files[0].file.name, 'a.txt')
})
