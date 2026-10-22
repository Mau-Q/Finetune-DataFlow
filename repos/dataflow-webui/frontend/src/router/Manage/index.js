import tool from '../tools'

const AsyncLoad = tool.AsyncLoad

export default {
    path: '/m',
    component: () => AsyncLoad(() => import('@/views/manage/index.vue')),
    children: [
        { path: 'training', component: () => AsyncLoad(() => import('@/views/manage/training/index.vue')), meta: { title: '模型训练' } },
        { path: 'multimodal', component: () => AsyncLoad(() => import('@/views/manage/multimodal/index.vue')), meta: { title: '图片 VQA' } },
        { path: 'generation', component: () => AsyncLoad(() => import('@/views/manage/generation/index.vue')), meta: { title: '文本生成' } },
        {
            path: 'materials',
            component: () => AsyncLoad(() => import('@/views/manage/library/index.vue')),
            props: { mode: 'materials' },
            meta: { title: '原始数据集' }
        },
        {
            path: 'training-datasets',
            component: () => AsyncLoad(() => import('@/views/manage/library/index.vue')),
            props: { mode: 'drafts' },
            meta: { title: '生成数据集' }
        },
        {
            path: '',
            component: () => AsyncLoad(() => import('@/views/manage/dataflow/index.vue'))
        },
        {
            path: 'serving',
            component: () => AsyncLoad(() => import('@/views/manage/serving/index.vue')),
            meta: {
                title: 'Dataflow-Serving'
            }
        },
        {
            path: 'dm',
            component: () => AsyncLoad(() => import('@/views/manage/dbManager/index.vue')),
            meta: {
                title: 'Dataflow-DBManager'
            }
        },
        {
            path: 'prompts',
            component: () => AsyncLoad(() => import('@/views/manage/prompts/index.vue')),
            meta: {
                title: 'Dataflow-Prompts'
            }
        },
        {
            path: 'schemas',
            component: () => AsyncLoad(() => import('@/views/manage/schemas/index.vue')),
            meta: {
                title: 'Dataflow-Schemas'
            }
        },
        {
            path: 'dataviz',
            component: () => AsyncLoad(() => import('@/views/manage/dataViz/index.vue')),
            meta: {
                title: 'Dataflow-DataViz'
            }
        },
        {
            path: 'settings',
            component: () => AsyncLoad(() => import('@/views/manage/settings/index.vue')),
            meta: {
                title: 'Dataflow-Settings'
            }
        },
        {
            path: 'analysis',
            component: () => AsyncLoad(() => import('@/views/manage/analysis/index.vue')),
            meta: {
                title: 'Dataflow-Analysis'
            }
        }
    ],
    meta: {
        title: 'Dataflow-WebUI'
    }
}
