export const PLATFORM_PIPELINES = [
    { id: 'platform-text', workflow: 'text', name: '文本生成', show: true, config: { operators: Array(13).fill(null) } },
    { id: 'platform-mm', workflow: 'multimodal', name: '图片 VQA', show: true, config: { operators: Array(4).fill(null) } }
]
