<template>
  <main class="generation" :class="{dark: theme === 'dark'}">
    <header><div><h1>文本生成</h1><p>选择 PDF 原始数据集，配置论文到 SFT 的 13 步流程。</p></div><button :disabled="busy" @click="load">刷新</button></header>
    <p v-if="error" role="alert" class="error">{{ error }}</p><p v-if="notice" role="status" class="notice">{{ notice }}</p>
    <section>
      <h2>生成配置</h2>
      <label>现有模板或配置<select :value="selectedId" @change="changeConfig"><option value="">新建 · 论文 PDF → 多跳 QA → 筛选 → SFT</option><option v-for="p in configs" :key="p.id" :value="p.id">{{ p.name }}</option></select></label>
      <form v-if="config" @submit.prevent="save">
        <div class="grid"><label>名称<input v-model="name" required maxlength="240" /></label><label>PDF 原始数据集<select v-model="datasetId" required><option value="">请选择</option><option v-for="d in pdfDatasets" :value="d.id" :key="d.id">{{ d.name }} · {{ d.file_count }} 个 PDF</option></select></label></div>
        <p v-if="datasetId && !pdfDatasets.some(d => d.id === datasetId)" class="error">当前配置的数据集不属于可用的纯 PDF 数据集，请重新选择。</p>
        <p v-if="!pdfDatasets.length" class="help">暂无纯 PDF 数据集，请先在原始数据集中导入 PDF。</p>
        <div class="grid"><label>统一分配文本服务<select v-model="servingId" @change="bindServing"><option value="">按各步骤配置</option><option v-for="s in servings" :key="s.id" :value="s.id">{{ s.name }}</option></select></label><label>请求失败后的额外重试次数<input type="number" min="0" max="5" v-model.number="config.execution_options.additional_retries" /></label></div>
        <p class="help">进度按整批计数。完整批次产物可复用；失败批次手动从头重跑，保留原任务。任务完成后仍需检查数据质量。</p>
        <details><summary>查看步骤与必要参数</summary><article v-for="(op, i) in config.operators" :key="i"><strong>{{ i+1 }}. {{ op.name }}</strong><p>{{ op.pipeline_role }}</p><label v-for="p in editable(op)" :key="p.name">{{ p.name }}<select v-if="p.name === 'llm_serving'" v-model="p.value"><option :value="null">未配置</option><option v-for="s in servings" :key="s.id" :value="s.id">{{ s.name }}</option></select><input v-else v-model="p.value" :type="typeof p.value === 'number' ? 'number' : 'text'" /></label></article></details>
        <div class="actions"><button :disabled="busy" type="submit">保存配置</button><button :disabled="busy || !selectedId" type="button" @click="openCanvas">进阶画布</button><button :disabled="busy || !selectedId" type="button" @click="check">检查运行条件</button><button class="primary" :disabled="busy || !selectedId || dirty" type="button" @click="showRunConfirm=true">提交运行</button></div>
        <p v-if="dirty" class="help">配置已修改，请先保存。</p><ul v-if="conditions"><li v-for="e in conditions.errors" :key="e" class="error">{{ e }}</li><li v-if="conditions.ready">运行条件检查通过；提交将调用所选文本服务。</li></ul>
      </form>
    </section>
    <div class="task-grid"><section><h2>任务记录</h2><p v-if="!tasks.length" class="help">暂无文本任务。历史画布任务仍在原任务面板中。</p><button class="task" v-for="t in tasks" :key="t.task_id" :class="{selected: task?.task_id === t.task_id}" @click="selectTask(t.task_id)"><strong>{{ t.name || t.task_id }}</strong><span>{{ statusLabel(t.status) }}</span><small>{{ t.task_id }} · {{ t.created_at || t.started_at }}</small></button></section>
      <section v-if="task"><h2>{{ task.name || '任务详情' }} · {{ statusLabel(task.status) }}</h2><p>{{ task.progress.completed }} / {{ task.progress.total }} 批次 · 已完成 {{ task.progress.steps_completed }} / {{ task.progress.steps_total }} 步</p><p v-if="task.retry_of">重跑来源：{{ task.retry_of }}</p><p class="error" v-if="failure">{{ failure }}</p>
        <div class="actions"><button :disabled="busy" @click="selectTask(task.task_id)">刷新详情</button><button v-if="['queued','running'].includes(task.status)" :disabled="busy" @click="cancel">终止任务</button><button v-if="['failed','cancelled','completed'].includes(task.status)" :disabled="busy" @click="retry">{{ task.status === 'completed' ? '复用完整产物' : '手动重跑整批' }}</button></div>
        <h3>产物清单</h3><p class="help">原始响应为算子解析前的模型文本；候选文件保留中间字段。只有训练产物可收集。</p><article v-for="a in task.output?.artifacts || []" :key="a.id"><div class="actions"><a :href="artifactUrl(a)" download>{{ kindLabel(a.kind) }} · {{ a.row_count }} 条</a><button v-if="a.kind === 'training'" :disabled="busy" @click="collect(a)">收集到草稿</button></div><small>{{ a.sha256 }}</small><p v-if="a.kind === 'training' && !a.row_count">0 条通过筛选；可保留完成结果，空草稿不能发布。</p></article>
        <label>收集目标<select v-model="draftId"><option value="">请选择生成数据集草稿</option><option v-for="d in drafts" :key="d.id" :value="d.id">{{ d.name }}</option></select></label><router-link to="/m/training-datasets">管理草稿与发布版本 →</router-link>
        <details><summary>输入、配置与资源快照</summary><pre>{{ JSON.stringify({config: task.pipeline_config, resources: task.resource_snapshots}, null, 2) }}</pre></details><details><summary>日志</summary><pre>{{ (task.logs || []).join('\n') }}</pre></details>
      </section>
    </div>
    <run-confirm-panel v-model="showRunConfirm" :theme="theme" :pipeline-name="name" :dataset-name="pdfDatasets.find(d=>d.id===datasetId)?.name || ''" :contract="{modality:'text',training_type:'sft'}" @confirm="submit" />
  </main>
</template>
<script>
import { useUnsavedChanges, confirmDiscard } from '@/components/manage/forms/unsaved'
import axios from 'axios'
import {mapState} from 'pinia'
import {useTheme} from '@/stores/theme'
import RunConfirmPanel from '@/components/manage/mainFlow/panels/runConfirmPanel.vue'
export default {
 setup(){useUnsavedChanges(vm=>!!vm.config && vm.dirty,vm=>{vm.config=null})},
 name: 'TextGeneration',
 components: {RunConfirmPanel},
 data:()=>({config:null, showRunConfirm:false, baseline:'', name:'论文 SFT 生成', selectedId:'',datasetId:'',servingId:'',configs:[],datasets:[],servings:[],tasks:[],task:null,drafts:[],draftId:'',conditions:null,busy:false,error:'',notice:'',timer:null}),
 computed:{...mapState(useTheme,['theme']),pdfDatasets(){return this.datasets.filter(d=>d.content_type==='pdf' && d.type==='jsonl')},dirty(){return this.baseline!==JSON.stringify([this.name,this.datasetId,this.config])},failure(){const o=this.task?.output||{};return [o.error,o.original_error,o.error_message,o.artifact_error].filter(Boolean).join('；')}},
 async mounted(){await this.load();this.timer=setInterval(()=>{if(!this.busy && this.task && ['queued','running'].includes(this.task.status))this.selectTask(this.task.task_id)},4000)},
 watch:{$route(to,from){if(to.path==='/m/generation' && from.path!==to.path && this.config){this.selectedId=to.query.pipeline||this.selectedId;this.selectConfig();this.load()}}},
 beforeUnmount(){clearInterval(this.timer)},
 methods:{
 async changeConfig(event){if(this.dirty && !await confirmDiscard(this)){event.target.value=this.selectedId;return}this.selectedId=event.target.value;this.selectConfig()},
 async request(method,path,data){const r=await axios({method,url:'/api/v1'+path,data});if(!r.data.success)throw new Error(r.data.message);return r.data.data},
 async action(fn){if(this.busy)return;this.busy=true;this.error='';this.notice='';try{await fn()}catch(e){this.error=e.response?.data?.message || e.response?.data?.detail || e.message}finally{this.busy=false}},
 async load(){await this.action(async()=>{[this.configs,this.datasets,this.servings,this.tasks,this.drafts]=await Promise.all(['/pipelines/','/datasets/?visible_only=true','/serving/','/generation/tasks','/library/drafts?visible_only=true'].map(p=>this.request('get',p)));this.drafts=this.drafts.filter(d=>d.training_type==='sft' && d.modality==='text');this.configs=this.configs.filter(p=>p.tags?.includes('platform-text'));if(!this.config){this.selectedId=this.$route.query.pipeline || '';await this.selectConfig();}if(this.$route.query.task)await this.fetchTask(this.$route.query.task)})},
 async selectConfig(){this.error='';this.conditions=null;this.servingId='';try{const p=this.selectedId?await this.request('get','/pipelines/'+this.selectedId):await this.request('get','/generation/template');this.config=JSON.parse(JSON.stringify(p.config));this.config.execution_options ||= {additional_retries:0};this.config.execution_options.additional_retries ??=0;this.datasetId=typeof this.config.input_dataset==='string'?this.config.input_dataset:this.config.input_dataset.id;this.name=this.selectedId?p.name:'论文 SFT 生成';this.baseline=JSON.stringify([this.name,this.datasetId,this.config])}catch(e){this.error=e.message}},
 bindServing(){if(this.servingId)for(const op of this.config.operators)for(const p of op.params.init)if(p.name==='llm_serving')p.value=this.servingId},
 editable(op){return op.params.init.filter(p=>['llm_serving','mineru_script','tokenizer_path','chunk_size','chunk_overlap','num_q','timeout_seconds'].includes(p.name))},
 save(){return this.action(async()=>{const c=JSON.parse(JSON.stringify(this.config));c.input_dataset=typeof c.input_dataset==='object'?{...c.input_dataset,id:this.datasetId}:{id:this.datasetId,location:[30,160]};const p=await this.request('post','/generation/configs',{name:this.name,config:c,pipeline_id:this.selectedId||null});this.selectedId=p.id;this.config=p.config;this.baseline=JSON.stringify([this.name,this.datasetId,this.config]);this.configs=(await this.request('get','/pipelines/')).filter(p=>p.tags?.includes('platform-text'));this.notice='已保存，与画布共用此配置';this.conditions=null})},
 check(){return this.action(async()=>{this.conditions=await this.request('get',`/generation/configs/${this.selectedId}/check`);if(this.dirty)this.notice='检查的是已保存配置，请先保存当前修改'})},
 submit(options){return this.action(async()=>{const r=await this.request('post',`/tasks/execute-async?pipeline_id=${encodeURIComponent(this.selectedId)}`,options);await this.fetchTask(r.task_id);this.tasks=await this.request('get','/generation/tasks');this.notice='任务已提交'})},
 openCanvas(){this.$router.push({path:'/m',query:{pipeline:this.selectedId}})},
 async fetchTask(id){this.task=await this.request('get','/generation/tasks/'+id)},selectTask(id){return this.action(()=>this.fetchTask(id))},
 cancel(){return this.action(async()=>{await this.request('post',`/tasks/execution/${this.task.task_id}/kill`);await this.fetchTask(this.task.task_id);this.tasks=await this.request('get','/generation/tasks')})},
 retry(){return this.action(async()=>{const r=await this.request('post',`/generation/tasks/${this.task.task_id}/retry`);await this.fetchTask(r.task_id);this.tasks=await this.request('get','/generation/tasks');this.notice=r.reused?'完整批次产物已核对，可直接收集':'已创建新任务，旧失败记录保留'})},
 collect(a){return this.action(async()=>{if(!this.draftId)throw new Error('请选择收集目标草稿');const r=await this.request('post',`/generation/tasks/${this.task.task_id}/collect`,{draft_id:this.draftId,artifact_id:a.id});this.notice=`已收集 ${r.added} 条训练样本`})},
 artifactUrl(a){return `/api/v1/generation/tasks/${this.task.task_id}/artifacts/${a.id}`},statusLabel(s){return {queued:'排队中',running:'运行中',completed:'已完成',failed:'失败',cancelled:'已取消'}[s]||s},kindLabel(k){return {raw_response:'原始模型响应',candidate:'候选 / 中间结果',training:'训练产物',invalid_samples:'无效样本记录'}[k]||k}
 }
}
</script>
<style scoped>
.generation{box-sizing:border-box;width:100%;height:100%;overflow:auto;padding:28px;background:#f7f8fb;color:#25334c;font-size:14px}header,.actions{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}header{margin-bottom:24px}h1{font-size:26px;margin:0 0 8px}h2{font-size:18px;margin:0 0 20px}p{line-height:1.7;margin:8px 0}section{background:white;border:1px solid #e2e7f0;border-radius:12px;padding:24px;margin-bottom:20px;min-width:0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}label{display:block;line-height:2;margin-bottom:16px}input,select{font:inherit;color:inherit;background:transparent;box-sizing:border-box;width:100%;padding:10px;border:1px solid #d9dfeb;border-radius:8px}button{cursor:pointer;font:inherit;padding:9px 16px;background:white;border:1px solid #d9dfeb;border-radius:8px;color:inherit}button:disabled{opacity:.5;cursor:default}.primary{background:#4e5bd5;color:white}a{color:#4e5bd5}small{display:block;overflow-wrap:anywhere;color:#78849a}.help,header p{color:#78849a}.error,.notice{padding:12px;border-radius:8px}.error{background:#fff0ed;color:#ae342b}.notice{background:#e9f4ed;color:#306448}.task-grid{display:grid;grid-template-columns:260px minmax(0,1fr);gap:20px}.task{text-align:left;display:grid;gap:6px;width:100%;margin-bottom:10px}.selected{border-color:#4e5bd5;background:#f0f2ff}article{padding:14px 0;border-bottom:1px solid #e2e7f0}summary{cursor:pointer;padding:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f8fb;padding:14px;max-height:400px;overflow:auto}.dark{background:#20242d;color:#dfe5ef}.dark section,.dark button{background:#292e39;border-color:#424b5b}.dark select,.dark input,.dark pre{background:#20242d;border-color:#424b5b}.dark .primary{background:#4e5bd5}@media(max-width:1100px){.task-grid,.grid{grid-template-columns:minmax(0,1fr)}}
</style>
