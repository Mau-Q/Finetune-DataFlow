// Adapt MM configuration to the existing canvas. Never register these steps in core.
const labels = {question:'生成问题',answer:'生成答案',validate:'结构检查',format:'训练格式整理'}
const field = (name,value) => ({name,value,show:true})
export function nativeMMGraph(config, flowId, styleDict) {
    const nodes = [{id:'db-node',type:'database-node',position:{x:30,y:160},deletable:false,
        data:{flowId,externalTemplate:true,operatorParams:{init:[],run:[field('image','image')]},label:'图片材料',name:'图片材料',num_samples:config.material_ids.length,
            keys:['image'],enableDelete:false,pipelineRole:'通过材料 ID 关联图片；点击 Switch 选择图片、服务与输出草稿。'}}]
    config.steps.forEach((s,i)=>{
        const tone=i<2?'generate':i===2?'filter':'refine'
        nodes.push({id:`mm-${s.id}`,type:'operator-node',position:{x:s.x+350,y:s.y+130},deletable:false,
            data:{...styleDict[tone],flowId,externalTemplate:true,enableDelete:false,
                name:s.kind.split(':')[1],label:s.kind.split(':')[1],status:labels[s.id],pipeline_idx:i+1,
                pipelineRole:`${labels[s.id]}：${Object.values(s.inputs).join(' + ')} → ${s.output}。`,
                mmStepId:s.id,operatorParams:{init:[field('resource_ref',s.resource_ref)],run:[
                    ...Object.entries(s.inputs).map(([k,v])=>field(`input_${k}`,v)),field('output',s.output),
                    ...Object.entries(s.bindings).map(([k,v])=>field(`binding_${k}`,v))]}}})
    })
    const edges=config.steps.map((s,i)=>({id:`mm-order-${i}`,type:'base-edge',
        source:i?`mm-${config.steps[i-1].id}`:'db-node',target:`mm-${s.id}`,
        sourceHandle:'node::source::node',targetHandle:'node::target::node',deletable:false,
        data:{label:'Node',edgeType:'node'}}))
    return {nodes,edges}
}
export function readNativeMM(config,nodes) {
    if (nodes.length !== config.steps.length + 1 || new Set(nodes.filter(n=>n.data?.mmStepId).map(n=>n.data.mmStepId)).size !== config.steps.length) throw new Error('MM 模板缺少步骤或包含额外节点，请重新打开配置')
    const result=JSON.parse(JSON.stringify(config))
    for (const step of result.steps) {
        const node=nodes.find(n=>n.data?.mmStepId===step.id)
        if(!node)throw new Error('MM 模板缺少步骤，请重新打开配置')
        const params=node.data.operatorParams
        const get=(section,name)=>{
            const p=params[section].find(p=>p.name===name)
            if(!p)throw new Error(`缺少字段 ${name}`)
            return p.value
        }
        step.resource_ref=get('init','resource_ref')
        for(const k of Object.keys(step.inputs))step.inputs[k]=get('run',`input_${k}`)
        step.bindings=Object.fromEntries(params.run.filter(p=>p.name.startsWith('binding_')).map(p=>[p.name.slice(8),p.value]))
        step.output=get('run','output')
        step.x=Math.round(node.position.x-350);step.y=Math.round(node.position.y-130)
        if(step.x<0||step.x>2000||step.y<0||step.y>1000)throw new Error('MM 节点超出可保存范围，请自动排版后重试')
    }
    return result
}
