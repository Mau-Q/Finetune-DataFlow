<template>
  <main class="mm" :class="{dark: theme === 'dark'}">
    <router-link :to="{path:'/m',query:{workflow:'multimodal',config:selectedId || undefined}}">返回原生 Pipeline 画布</router-link>
    <header><div><h1>图片 VQA</h1><p>从图片生成问题和答案，检查结构并整理为图文 SFT 样本。</p></div><button :disabled="busy" @click="load">刷新列表</button></header>
    <p class="status">未做真实运行验证。当前仅支持模板配置，独立 MM 执行尚未启用。需要通过视觉 API 生成图文数据，请使用代表性图文流程：<router-link :to="{path:'/m',query:{pipeline:'representative-image_text-sft-v1'}}">图文 SFT</router-link> · <router-link :to="{path:'/m',query:{pipeline:'representative-image_text-dpo-v1'}}">图文 DPO</router-link>。</p>
    <p class="error" role="alert" v-if="error">{{ error }}</p><p role="status" v-if="notice">{{ notice }}</p>
    <form v-if="config" @submit.prevent="save">
      <section><h2>输入与输出</h2>
        <label>配置<select :value="selectedId" @change="changeConfig"><option value="">新建 · MM 基础图片 VQA</option><option v-for="r in configs" :key="r.id" :value="r.id">{{ r.name }}</option></select></label>
        <label>名称<input v-model="name" required maxlength="240" /></label>
        <p><router-link to="/m/materials">管理图片材料</router-link> · <router-link to="/m/training-datasets">管理图文草稿</router-link></p>
        <fieldset><legend>图片材料</legend><p v-if="!images.length">暂无图片，请先在材料管理中导入。</p><label v-for="m in images" :key="m.id" class="image"><input type="checkbox" :value="m.id" v-model="config.material_ids" /><img :src="`/api/v1/library/materials/${m.id}/file`" alt="" />{{ m.name }}</label></fieldset>
        <label>输出到图文 SFT 草稿<select v-model="config.draft_id"><option :value="null">稍后选择</option><option v-for="d in drafts" :key="d.id" :value="d.id">{{ d.name }}</option></select></label>
        <p>输出契约：messages + media_bindings。图片通过材料 ID 显式关联；后续可使用共用草稿、发布和媒体打包功能。</p>
        <label>视觉服务引用（可留空）<input v-model="config.vision_service_id" placeholder="未配置视觉服务" /></label>
        <p>服务引用只保存配置；填写后仍需独立执行适配与视觉能力验证。</p>
        <div class="grid"><label>最大并发<input type="number" min="1" max="32" v-model.number="config.max_workers" /></label><label>超时（秒）<input type="number" min="1" max="7200" v-model.number="config.timeout" /></label></div>
      </section>
      <section><h2>流程与字段绑定</h2><p>两步生成分别使用问题和答案提示词。节点坐标与下方步骤编辑共用同一配置。</p>
        <div class="canvas"><div :style="{width: canvasWidth+'px', height: canvasHeight+'px'}"><div class="node" v-for="(s,i) in config.steps" :key="s.id" :style="{left:s.x+'px',top:s.y+'px'}">{{ i+1 }}. {{ labels[s.id] }}<small>{{ Object.values(s.inputs).join(' + ') }} → {{ s.output }}</small></div></div></div>
        <article v-for="s in config.steps" :key="s.id"><h3>{{ labels[s.id] }}</h3><p>{{ s.kind.startsWith('mm:') ? 'DataFlow-MM · PromptedVQAGenerator' : '共用训练数据契约' }}</p>
          <label v-if="s.id!=='format'">{{ s.id==='validate'?'Schema 引用':'Prompt 引用' }}<select v-model="s.resource_ref" @change="resourceChanged(s)"><option :value="defaultRefs[s.id]">内置 · {{ labels[s.id] }}</option><option v-for="r in (s.id==='validate'?schemas.filter(r=>r.purpose!=='训练样本校验'):prompts)" :key="r.id" :value="(s.id==='validate'?'schema_ref:':'user_prompt:')+r.id">{{ r.name }}</option></select></label>
          <router-link v-if="s.id!=='format'" :to="{path:s.id==='validate'?'/m/schemas':'/m/prompts',query:{pipeline:selectedId?'multimodal:'+selectedId:'template:image-sft',relation:'compatible',...(s.id==='validate'?{}:{operator:'PromptedVQAGenerator'})}}">{{ s.id==='validate'?'管理 Schema':'管理 Prompt' }}</router-link>
          <pre v-if="resourceContent(s)">{{ resourceContent(s) }}</pre>
          <div class="grid"><label v-for="(_,k) in s.inputs" :key="k">输入 {{ k }}<input v-model="s.inputs[k]" /></label><label>输出字段<input v-model="s.output" :readonly="s.id==='format'" /></label></div>
          <div class="grid"><label v-for="(_,k) in s.bindings" :key="k">提示词变量 {{ k }}<input v-model="s.bindings[k]" /></label><label>节点 X<input type="number" min="0" max="2000" v-model.number="s.x" /></label><label>节点 Y<input type="number" min="0" max="1000" v-model.number="s.y" /></label></div>
        </article>
      </section>
      <section><div class="actions"><button type="submit" :disabled="busy">保存配置草稿</button><button type="button" :disabled="busy || !selectedId || dirty" @click="check">检查运行条件</button><button type="button" :disabled="busy || !selectedId || dirty" @click="submit">提交运行</button></div><p v-if="dirty">有未保存修改，请先保存。</p><p v-if="conditions">结构检查：{{ conditions.structure_valid ? '通过' : '未通过' }}</p><ul v-if="conditions"><li v-for="e in conditions.errors" :key="e">{{ e }}</li></ul></section>
    </form>
  </main>
</template>
<script>
import { useUnsavedChanges, confirmDiscard } from '@/components/manage/forms/unsaved'
import axios from 'axios'
import {mapState} from 'pinia'
import {useTheme} from '@/stores/theme'
export default {
 setup(){useUnsavedChanges(vm=>!!vm.config && vm.dirty,vm=>{vm.config=null})},
 name:'MultimodalConfiguration',
 data:()=>({config:null,name:'图片 VQA 配置',selectedId:'',configs:[],images:[],drafts:[],prompts:[],schemas:[],builtins:{},defaultRefs:{},baseline:'',busy:false,error:'',notice:'',conditions:null,labels:{question:'生成问题',answer:'生成答案',validate:'结构检查',format:'训练格式整理'}}),
 computed:{...mapState(useTheme,['theme']),dirty(){return this.baseline!==JSON.stringify([this.name,this.config])},canvasWidth(){return Math.max(1180,...this.config.steps.map(s=>s.x+270))},canvasHeight(){return Math.max(150,...this.config.steps.map(s=>s.y+110))}},
 watch:{$route(to){if(this.config && to.path==='/m/multimodal' && to.query.config && to.query.config!==this.selectedId){this.selectedId=to.query.config;this.open()}}},
 async mounted(){await this.load();if(this.$route.query.config){this.selectedId=this.$route.query.config;await this.open()}} ,
 methods:{
 async changeConfig(event){if(this.dirty && !await confirmDiscard(this)){event.target.value=this.selectedId;return}this.selectedId=event.target.value;this.open()},
 async request(method,path,data){const r=await axios({method,url:'/api/v1'+path,data});if(!r.data.success)throw new Error(r.data.message);return r.data.data},
 async action(fn){if(this.busy)return;this.busy=true;this.error='';this.notice='';try{await fn()}catch(e){this.error=e.response?.data?.detail||e.response?.data?.message||e.message}finally{this.busy=false}},
 load(){return this.action(async()=>{const [t,configs,materials,drafts,prompts,schemas]=await Promise.all(['/multimodal/template','/multimodal/configs','/library/materials','/library/drafts','/prompts/user','/json_schemas?include_builtin=true'].map(p=>this.request('get',p)));this.configs=configs;this.images=materials.filter(m=>m.kind==='image');this.drafts=drafts.filter(d=>d.modality==='image_text'&&d.training_type==='sft');this.prompts=prompts;this.schemas=schemas;this.builtins=t.builtin_resources;this.defaultRefs=Object.fromEntries(t.config.steps.map(s=>[s.id,s.resource_ref]));if(!this.config){this.config=t.config;this.name=t.name;this.baseline=JSON.stringify([this.name,this.config])}})},
 open(){return this.action(async()=>{const r=await this.request('get',this.selectedId?'/multimodal/configs/'+this.selectedId:'/multimodal/template');this.config=r.config;this.name=r.name;this.baseline=JSON.stringify([this.name,this.config]);this.conditions=null})},
 save(){return this.action(async()=>{const r=await this.request('post','/multimodal/configs',{name:this.name,config:this.config,config_id:this.selectedId||null});this.selectedId=r.id;this.config=r.config;this.name=r.name;this.baseline=JSON.stringify([this.name,this.config]);this.configs=await this.request('get','/multimodal/configs');this.conditions=null;this.notice='已保存配置草稿；未做真实运行验证'})},
 check(){return this.action(async()=>{this.conditions=await this.request('get',`/multimodal/configs/${this.selectedId}/check`)})},
 submit(){return this.action(async()=>{await this.request('post',`/multimodal/configs/${this.selectedId}/submit`)})},
 resourceContent(s){if(this.builtins[s.resource_ref])return this.builtins[s.resource_ref];const [type,id]=s.resource_ref.split(':');const r=(type==='schema_ref'?this.schemas:this.prompts).find(r=>r.id===id);return r?.template||r?.schema},
 resourceChanged(s){if(!['question','answer'].includes(s.id))return;const text=this.resourceContent(s)||'';const vars=[...text.matchAll(/(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})/g)].map(m=>m[1]);s.bindings=Object.fromEntries(vars.map(k=>[k,s.inputs[k]||k]))}
 }
}
</script>
<style scoped>
.mm{flex:1;min-width:0;box-sizing:border-box;height:100%;overflow:auto;padding:28px;background:#f7f8fb;color:#25334c;font-size:14px}header,.actions{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}h1{margin:0}h2{font-size:19px}p{line-height:1.7}section{background:white;border:1px solid #e2e7f0;border-radius:12px;padding:24px;margin:20px 0}label{display:block;margin:12px 0;line-height:2}input,select,button{font:inherit;color:inherit;background:white;border:1px solid #d9dfeb;border-radius:7px;padding:9px;box-sizing:border-box}input,select{width:100%}button{cursor:pointer}button:disabled{opacity:.5}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}article{border-top:1px solid #e2e7f0;padding:14px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f8fb;padding:12px;max-height:220px;overflow:auto}.status{background:#fff4d7;padding:14px;border-radius:8px}.error{color:#ae342b;background:#fff0ed;padding:14px}a{color:#4e5bd5}.image{display:inline-flex;gap:10px;align-items:center;margin-right:20px}.image input{width:auto}.image img{width:50px;height:50px;object-fit:contain}fieldset{border:1px solid #d9dfeb;border-radius:8px}.canvas{overflow:auto;border:1px solid #d9dfeb;border-radius:8px}.canvas>div{position:relative}.node{position:absolute;width:240px;background:#eff1ff;border:1px solid #a6afea;border-radius:10px;padding:14px;box-sizing:border-box}small{display:block;margin-top:10px;overflow-wrap:anywhere}.dark{background:#20242d;color:#dfe5ef}.dark section,.dark input,.dark select,.dark button,.dark pre{background:#292e39;border-color:#424b5b}.dark .node{background:#343b60}.dark .status{background:#51492d}@media(max-width:900px){.grid{grid-template-columns:1fr}.mm{padding:16px}}
</style>
