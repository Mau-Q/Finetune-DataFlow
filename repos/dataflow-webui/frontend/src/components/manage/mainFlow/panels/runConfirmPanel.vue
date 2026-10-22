<template>
    <base-panel v-model="visible" title="运行 Pipeline" width="560px" height="680px" :theme="theme" :teleport="true">
        <template #content>
            <div class="run-confirm" :class="{ dark: theme === 'dark' }">
                <div class="run-summary"><i class="ms-Icon ms-Icon--Play" aria-hidden="true"></i><div><strong>{{ pipelineName }}</strong><p>原始数据集：{{ datasetName || '未选择' }}</p></div></div>
                <section class="collection-settings">
                    <strong>生成完成后自动收录到</strong>
                    <div class="collection-modes">
                        <label :class="{selected:collectionMode==='new'}"><input v-model="collectionMode" type="radio" value="new" :disabled="busy || loading" /> 新建数据集</label>
                        <label :class="{selected:collectionMode==='append'}"><input v-model="collectionMode" type="radio" value="append" :disabled="busy || loading" /> 追加到已有数据集</label>
                    </div>
                    <label v-if="collectionMode === 'new'" class="collection-field">新数据集名称
                        <input v-model="collectionName" aria-label="新数据集名称" maxlength="240" :disabled="busy || loading" />
                    </label>
                    <label v-else class="collection-field">目标生成数据集
                        <select v-model="draftId" aria-label="目标生成数据集" :disabled="busy || loading">
                            <option value="">请选择数据集</option>
                            <option v-for="d in compatibleDrafts" :key="d.id" :value="d.id">{{ d.name }} · {{ d.row_count }} 条</option>
                        </select>
                    </label>
                    <p class="help">记住本类流程上次的选择；本次生成成功后直接收录，无需再次确认。</p>
                    <p v-if="collectionMode === 'append' && !compatibleDrafts.length" class="help">暂无类型匹配的数据集，请选择新建数据集。</p>
                </section>
                <div class="output-heading"><strong>结果保存位置</strong><fv-button :theme="theme" icon="FolderOpen" :disabled="busy || loading" :border-radius="6" @click="editing = !editing">{{ editing ? '收起' : '更改' }}</fv-button></div>
                <p class="help">{{ editing ? '为本次运行选择结果根目录，程序会创建独立子目录。' : '自动保存到本地任务目录，每次运行独立保存。' }}</p>
                <fv-button v-if="editing" :theme="theme" icon="FolderOpen" :disabled="busy || loading" :border-radius="6" style="margin-bottom:8px" @click="choose">选择文件夹</fv-button>
                <fv-text-box v-if="editing" v-model="outputRoot" :theme="theme" aria-label="本次结果根目录" placeholder="输入本机绝对目录路径" :border-radius="6" :disabled="busy || loading" style="width:100%;height:38px" />
                <p v-else class="directory">{{ outputRoot || '正在读取…' }}</p>
                <p class="path-note">本次子目录将在提交时生成，包含时间和任务 ID。</p>
                <p v-if="error" role="alert" class="error">{{ error }}</p>
            </div>
        </template>
        <template #control>
            <fv-button :theme="theme" :disabled="busy" :border-radius="8" style="width:100px;margin-right:8px" @click="visible = false">取消</fv-button>
            <fv-button theme="dark" background="#4e5bd5" :disabled="loading || busy || !outputRoot.trim() || !validTarget" :border-radius="8" style="width:120px" @click="confirm">{{ busy ? '正在检查…' : '开始运行' }}</fv-button>
        </template>
    </base-panel>
</template>
<script>
import axios from 'axios'
import BasePanel from '@/components/general/basePanel.vue'
export default {
    components: { BasePanel },
    props: { modelValue: Boolean, pipelineName: {type:String,default:'Pipeline'}, datasetName: {type:String,default:''}, theme: {type:String,default:'light'}, contract: {type:Object,default:null} },
    emits: ['update:modelValue', 'confirm'],
    data: () => ({ outputRoot: '', editing: false, busy: false, loading: false, error: '', generation: 0, collectionMode: 'new', collectionName: '', draftId: '', drafts: [] }),
    computed: {
        visible: {get(){return this.modelValue},set(v){this.$emit('update:modelValue',v)}},
        compatibleDrafts() { return this.drafts.filter(d => !this.contract || (d.modality === this.contract.modality && (d.training_type || 'sft') === this.contract.training_type)) },
        validTarget() { return this.collectionMode === 'new' ? !!this.collectionName.trim() : this.compatibleDrafts.some(d => d.id === this.draftId) },
        preferenceKey() { return this.contract ? `${this.contract.modality}:${this.contract.training_type}` : 'general' }
    },
    watch: { modelValue(val) { if(val)this.load() } },
    methods: {
        async request(method,path,data) { const r=await axios({method,url:'/api/v1/tasks/result-storage'+path,data}); if(!r.data.success)throw new Error(r.data.message);return r.data.data },
        async load() {
            const generation=++this.generation
            this.loading=true; this.error=''; this.editing=false
            this.collectionMode='new'; this.collectionName=this.pipelineName; this.draftId=''
            try {
                const [storage,prefs,drafts] = await Promise.all([
                    this.request('get',''), axios.get('/api/v1/tasks/collection-target'), axios.get('/api/v1/library/drafts?visible_only=true')])
                if(generation !== this.generation || !this.visible)return
                if(!prefs.data.success || !drafts.data.success)throw new Error(prefs.data.message || drafts.data.message)
                this.outputRoot=storage.output_root; this.drafts=drafts.data.data
                const last=prefs.data.data[this.preferenceKey]
                if(last?.mode === 'new')this.collectionName=last.name || this.pipelineName
                if(last?.mode === 'append' && this.compatibleDrafts.some(d => d.id === last.draft_id)) {
                    this.collectionMode='append'; this.draftId=last.draft_id
                }
            } catch(e) {if(generation===this.generation)this.error=e.message}
            finally {if(generation===this.generation)this.loading=false}
        },
        async choose() { this.busy=true;this.error='';try{const r=await this.request('post','/choose');if(!r.cancelled)this.outputRoot=r.output_root}catch(e){this.error=e.response?.data?.message||e.message}finally{this.busy=false} },
        async confirm() { if(this.busy || this.loading || !this.validTarget)return;this.busy=true;this.error='';try{const r=await this.request('post','/check',{output_root:this.outputRoot});this.visible=false;this.$emit('confirm',{output_root:r.output_root,collection_target:{mode:this.collectionMode,name:this.collectionMode==='new'?this.collectionName.trim():'',draft_id:this.collectionMode==='append'?this.draftId:null}})}catch(e){this.error=e.response?.data?.message||e.message}finally{this.busy=false} }
    }
}
</script>
<style scoped>
.run-confirm{box-sizing:border-box;padding:18px 12px;color:#26334d;overflow:auto;height:100%}.dark{color:#eee}.run-summary{display:flex;gap:14px;align-items:center;margin-bottom:24px}.run-summary i{font-size:25px;color:#4e5bd5}.run-summary p{margin:8px 0 0;font-size:13px}.output-heading{display:flex;justify-content:space-between;align-items:center}.help,.path-note{font-size:13px;line-height:1.7;color:#76839a}.directory{padding:12px;background:rgba(120,130,150,.08);border-radius:6px;overflow-wrap:anywhere;font-size:13px}.error{color:#b63830;line-height:1.6}
.collection-modes label{display:flex;align-items:center;gap:7px;padding:9px 12px;border:1px solid #c4cad8;border-radius:6px;cursor:pointer}.collection-modes label.selected{border-color:#4e5bd5;background:rgba(78,91,213,.08)}.collection-modes input{appearance:auto;display:inline-block;width:14px;height:14px;opacity:1;position:static;margin:0;accent-color:#4e5bd5}.collection-settings{margin-bottom:24px}.collection-modes{display:flex;gap:24px;margin:16px 0}.collection-field{display:flex;flex-direction:column;gap:8px;font-size:14px}.collection-field input,.collection-field select{box-sizing:border-box;width:100%;padding:10px;border:1px solid #c4cad8;border-radius:6px;background:transparent;color:inherit;font:inherit}.dark option{background:#252833}
</style>
