import test from 'node:test'
import assert from 'node:assert/strict'
import {defaultFilters, filterCatalog, activeFilters} from './filters.js'
const apply=(rows,values,mode='drafts')=>filterCatalog(rows,{...defaultFilters(),...values},mode)
test('original datasets filter by actual material form, independently of manifest encoding',()=>{
 const rows=[{id:'pdf',name:' Paper ',type:'jsonl',content_type:'pdf'},{id:'data',name:'Rows',type:'jsonl'},{id:'unknown',name:'Legacy'}]
 assert.deepEqual(apply(rows,{search:'PAPER',sourceForm:'PDF'},'materials').map(r=>r.id),['pdf'])
 assert.deepEqual(apply(rows,{sourceForm:'结构化数据'},'materials').map(r=>r.id),['data'])
 assert.equal(apply(rows,{search:'missing'},'materials').length,0)
 assert.equal(rows[0].id,'pdf')
})
test('draft filters combine modality, contract, publication and sample existence',()=>{
 const rows=[{name:'A',modality:'text',training_type:'sft',row_count:3,latest_release_version:2,status:'draft'}, {name:'B',modality:'image_text',training_type:'dpo',row_count:0}, {name:'Legacy',modality:'text',row_count:1}]
 assert.deepEqual(apply(rows,{modality:'text',trainingType:'sft',release:'published',samples:'nonempty'}).map(r=>r.name),['A'])
 assert.deepEqual(apply(rows,{modality:'image_text',trainingType:'dpo',release:'unpublished',samples:'empty'}).map(r=>r.name),['B'])
 assert.equal(apply(rows,{trainingType:'sft'}).length,2)
 assert.equal(activeFilters({...defaultFilters(),search:'  abc ',release:'published'},'drafts').length,2)
})
test('sorting handles absent dates and never mutates the catalog',()=>{
 const rows=[{name:'Z'},{name:'B',updated_at:'2026-01-02'},{name:'A',created_at:'2026-01-01'}]
 assert.deepEqual(apply(rows,{sort:'recent'}).map(r=>r.name),['B','A','Z'])
 assert.deepEqual(apply(rows,{sort:'oldest'}).map(r=>r.name),['A','B','Z'])
 assert.deepEqual(apply(rows,{sort:'name'}).map(r=>r.name),['A','B','Z'])
 assert.deepEqual(rows.map(r=>r.name),['Z','B','A'])
})
