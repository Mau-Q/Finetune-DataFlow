<template>
  <section class="lifecycle">
    <draft-review-status :draft="draft" /><h3>整理与发布</h3><p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <details><summary>编辑或删除当前页样本</summary><label>样本<select :value="index" @change="selectRow"><option v-for="(id,i) in draft.sample_ids || []" :key="id" :value="i">样本 {{ draft.offset+i+1 }} · {{ id.slice(0,16) }}</option></select></label>
      <template v-if="draft.rows?.[index]"><template v-if="draft.training_type === 'dpo'"><label v-for="key in ['prompt','chosen','rejected']" :key="key">{{ fieldLabel(key) }}<textarea v-model="edited[key]" rows="3" /></label></template><template v-else-if="!edited.messages"><label v-for="key in ['instruction','input','output']" :key="key">{{ fieldLabel(key) }}<textarea v-model="edited[key]" rows="3" /></label></template>
      <label v-else>对话样本<textarea v-model="messageJson" rows="10" /></label><details><summary>来源任务与样本标识</summary><pre>{{ draft.sample_ids?.[index] }}
{{ JSON.stringify(draft.sample_sources?.[draft.sample_ids?.[index]] || [], null, 2) }}</pre></details>
      <div class="actions"><button :disabled="busy" @click="edit">保存样本</button><button :disabled="busy" @click="remove">删除样本</button><button v-if="dirty" :disabled="busy" @click="cancelRow">取消编辑</button></div></template>
    </details>
    <details v-if="draft.training_type !== 'dpo'"><summary>字段映射（应用于整个草稿）</summary><p>将已有字段复制到训练字段，原字段保留。</p><label v-for="target in ['instruction','input','output']" :key="target">{{ fieldLabel(target) }}<select v-model="mapping[target]"><option v-if="target==='input'" value="">空输入</option><option v-for="field in draft.fields" :key="field" :value="field">{{ field }}</option></select></label><button :disabled="busy || dirty" @click="mapFields">应用映射</button></details>
    <div class="actions"><p>发布会固定当前样本、来源及图片。后续编辑不改变已有版本。</p><button class="primary" :disabled="busy || dirty || !draft.row_count" @click="publish">发布新版本</button></div>
    <p v-if="dirty" role="status">有未保存的样本修改，请先保存或取消编辑，再发布。</p><h3>已发布版本</h3><p v-if="!releases.length">暂无版本。</p><article v-for="r in releases" :key="r.id"><div class="actions"><strong>v{{ r.version }} · {{ r.row_count }} 条</strong><span>{{ new Date(r.created_at).toLocaleString() }}</span></div><div class="actions"><a :href="url(r,'package')" download>下载数据与媒体包</a><a :href="url(r,'jsonl')" download>基础 JSONL</a><a v-if="r.formats.includes('alpaca')" :href="url(r,'alpaca')" download>instruction / input / output</a><button :disabled="busy" @click="fork(r)">从此版本建新草稿</button></div><details><summary>版本内容哈希与媒体清单</summary><pre>{{ JSON.stringify(r,null,2) }}</pre></details></article>
  </section>
</template>
<script>
import axios from 'axios'
import DraftReviewStatus from '@/components/manage/team/DraftReviewStatus.vue'
import { useUnsavedChanges, confirmDiscard, confirmAction } from '@/components/manage/forms/unsaved'
import { publishChange } from '@/components/manage/forms/changes'
export default{
 components:{DraftReviewStatus},
 setup(){useUnsavedChanges(vm=>vm.dirty,vm=>vm.loadRow())},
 props:{draft:{type:Object,required:true}},emits:['updated','forked','dirty-change'],
 data:()=>({baseline:'',baselineMessage:'',index:0,edited:{},messageJson:'',mapping:{instruction:'instruction',input:'input',output:'output'},releases:[],busy:false,error:'',notice:''}),
 computed:{dirty(){return !!this.draft.rows?.[this.index] && (this.edited.messages?this.messageJson!==this.baselineMessage:JSON.stringify(this.edited)!==this.baseline)}},
 beforeUnmount(){this.$emit('dirty-change',false)},
 watch:{dirty:{flush:'sync',handler(value){this.$emit('dirty-change',value)}},draft:{immediate:true,handler(){this.index=0;this.loadRow();this.loadReleases()}}},
 methods:{
 fieldLabel(k){return {instruction:'指令（instruction）',input:'输入（input）',output:'回答（output）',prompt:'问题（prompt）',chosen:'优选回答（chosen）',rejected:'较差回答（rejected）'}[k]},
 async request(method,path,data){const r=await axios({method,url:'/api/v1/generation'+path,data});if(!r.data.success)throw new Error(r.data.message);return r.data.data},
 async action(fn){if(this.busy)return;this.busy=true;this.error='';this.notice='';try{await fn()}catch(e){this.error=e.response?.data?.message||e.message}finally{this.busy=false}},
 async selectRow(event){const next=Number(event.target.value);if(this.dirty && !await confirmDiscard(this)){event.target.value=this.index;return}this.index=next;this.loadRow()},
 cancelRow(){this.loadRow();this.error='';this.notice='当前修改已取消。'},
 loadRow(){this.edited=JSON.parse(JSON.stringify(this.draft.rows?.[this.index]||{}));this.messageJson=JSON.stringify(this.edited,null,2);this.baseline=JSON.stringify(this.edited);this.baselineMessage=this.messageJson},
 async loadReleases(){const id=this.draft.id;try{const records=await this.request('get',`/drafts/${id}/releases`);if(id===this.draft.id)this.releases=records}catch(e){this.error=e.message}},
 edit(){return this.action(async()=>{const row=this.edited.messages?JSON.parse(this.messageJson):this.edited;await this.request('put',`/drafts/${this.draft.id}/samples/${this.draft.sample_ids[this.index]}`,{row,expected_updated_at:this.draft.updated_at});this.baseline=JSON.stringify(this.edited);this.baselineMessage=this.messageJson;this.notice='样本已保存';publishChange('datasets',this.draft.id);this.$emit('updated')})},
 async remove(){if(!await confirmAction(this,`删除「${this.draft.name}」的样本 ${this.draft.offset+this.index+1}？已发布版本不受影响。`,'error'))return;return this.action(async()=>{await this.request('delete',`/drafts/${this.draft.id}/samples/${this.draft.sample_ids[this.index]}`);this.notice='样本已删除';publishChange('datasets',this.draft.id);this.$emit('updated')})},
 mapFields(){return this.action(async()=>{await this.request('post',`/drafts/${this.draft.id}/map-fields`,{mapping:this.mapping});this.notice='字段映射已应用';publishChange('datasets',this.draft.id);this.$emit('updated')})},
 publish(){return this.action(async()=>{const r=await this.request('post',`/drafts/${this.draft.id}/publish`);await this.loadReleases();publishChange('datasets',this.draft.id);this.$emit('updated');this.notice=`已发布 v${r.version}`})},
 fork(r){return this.action(async()=>{const draft=await this.request('post',`/releases/${r.id}/fork`);publishChange('datasets',draft.id);this.$emit('forked',draft);this.notice='新草稿已创建'})},
 url(r,f){return `/api/v1/generation/releases/${r.id}/download?format=${f}`}
 }
}
</script>
<style scoped>
.lifecycle{margin-top:24px;border-top:1px solid #d9dfeb;padding-top:12px}summary{cursor:pointer;padding:12px 0}label{display:block;line-height:2;margin:12px 0}textarea,select{box-sizing:border-box;display:block;width:100%;padding:10px;border:1px solid #d9dfeb;border-radius:8px;font:inherit;color:inherit;background:transparent}.actions{display:flex;align-items:center;gap:12px;justify-content:space-between;flex-wrap:wrap;margin:14px 0}button{border:1px solid #d9dfeb;border-radius:8px;background:transparent;color:inherit;cursor:pointer;padding:9px 16px;font:inherit}button:disabled{opacity:.5;cursor:default}.primary{background:#4e5bd5;color:white}.error{color:#ae342b;background:#fff0ed;padding:12px;border-radius:7px}p{line-height:1.7}a{color:#4e5bd5}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:300px;overflow:auto}article{padding:12px 0;border-bottom:1px solid #d9dfeb}
</style>
