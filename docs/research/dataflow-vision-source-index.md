# DataFlow 与 DataFlow-MM 相关源码索引

本索引由 `scripts/research/inventory_dataflow_vision.py` 从固定源码生成。它列出声明与调用位置，不代表全部算子已安装依赖、执行或通过质量验收。完整签名和 Pipeline 调用见本地 `outputs/dataflow-mm-research-2026-10-19/inventory.json`。

## core：`769a99e0563a7ad63b451dc0f3a9854cd9c1a182`

### 算子

| 类 | 类别/步骤 | 父模块惰性导出 | 源码 |
| --- | --- | --- | --- |
| `BenchDatasetEvaluator` | core_text/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/eval/bench_dataset_evaluator.py) |
| `BenchDatasetEvaluatorQuestion` | core_text/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/eval/bench_dataset_evaluator_question.py) |
| `PromptedEvaluator` | core_text/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/eval/prompted_eval.py) |
| `Text2QASampleEvaluator` | core_text/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/eval/text2qa_sample_evaluator.py) |
| `UnifiedBenchDatasetEvaluator` | core_text/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/eval/unified_bench_dataset_evaluator.py) |
| `GeneralFilter` | core_text/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/filter/general_filter.py) |
| `KCenterGreedyFilter` | core_text/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/filter/kcentergreedy_filter.py) |
| `PromptedFilter` | core_text/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/filter/prompted_filter.py) |
| `BenchAnswerGenerator` | core_text/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/generate/bench_answer_generator.py) |
| `ChunkedPromptedGenerator` | core_text/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/generate/chunked_prompted_generator.py) |
| `EmbeddingGenerator` | core_text/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/generate/embedding_generator.py) |
| `FormatStrPromptedGenerator` | core_text/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/generate/format_str_prompted_generator.py) |
| `PromptedGenerator` | core_text/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/generate/prompted_generator.py) |
| `RandomDomainKnowledgeRowGenerator` | core_text/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/generate/random_domain_knowledge_row_generator.py) |
| `RetrievalGenerator` | core_text/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/generate/retrieval_generator.py) |
| `Text2MultiHopQAGenerator` | core_text/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/generate/text2multihopqa_generator.py) |
| `Text2QAGenerator` | core_text/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/generate/text2qa_generator.py) |
| `PandasOperator` | core_text/refine | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/refine/pandas_operator.py) |
| `PromptedRefiner` | core_text/refine | 是 | [文件](../../repos/dataflow/dataflow/operators/core_text/refine/prompted_refiner.py) |
| `AlpagasusSampleEvaluator` | text_sft/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/eval/alpagasus_sample_evaluator.py) |
| `DeitaComplexitySampleEvaluator` | text_sft/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/eval/deita_complexity_sample_evaluator.py) |
| `DeitaQualitySampleEvaluator` | text_sft/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/eval/deita_quality_sample_evaluator.py) |
| `InstagSampleEvaluator` | text_sft/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/eval/instag_sample_evaluator.py) |
| `MMDDatasetEvaluator` | text_sft/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/eval/mmd_dataset_evaluator.py) |
| `RMSampleEvaluator` | text_sft/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/eval/rm_sample_evaluator.py) |
| `SuperfilteringSampleEvaluator` | text_sft/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/eval/superfiltering_sample_evaluator.py) |
| `TreeinstructSampleEvaluator` | text_sft/eval | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/eval/treeinstruct_sample_evaluator.py) |
| `AlpagasusFilter` | text_sft/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/filter/alpagasus_filter.py) |
| `DeitaComplexityFilter` | text_sft/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/filter/deita_complexity_filter.py) |
| `DeitaQualityFilter` | text_sft/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/filter/deita_quality_filter.py) |
| `InstagFilter` | text_sft/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/filter/instag_filter.py) |
| `RMFilter` | text_sft/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/filter/rm_filter.py) |
| `SuperfilteringFilter` | text_sft/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/filter/superfiltering_filter.py) |
| `TreeinstructFilter` | text_sft/filter | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/filter/treeinstruct_filter.py) |
| `CondorGenerator` | text_sft/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/generate/condor_generator.py) |
| `SFTGeneratorSeed` | text_sft/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/generate/sft_generator_from_seed.py) |
| `CondorRefiner` | text_sft/refine | 是 | [文件](../../repos/dataflow/dataflow/operators/text_sft/refine/condor_refiner.py) |
| `KBCChunkGenerator` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/kbc_chunk_generator.py) |
| `KBCChunkGeneratorBatch` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/kbc_chunk_generator_batch.py) |
| `KBCMultiHopQAGeneratorBatch` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/kbc_multihop_qa_generator_batch.py) |
| `KBCTextCleaner` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/kbc_text_cleaner.py) |
| `KBCTextCleanerBatch` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/kbc_text_cleaner_batch.py) |
| `MathBookQuestionExtract` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/mathbook_question_extract.py) |
| `FileOrURLToMarkdownConverterAPI` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/mineru_operators.py) |
| `FileOrURLToMarkdownConverterLocal` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/mineru_operators.py) |
| `FileOrURLToMarkdownConverterFlash` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/mineru_operators.py) |
| `QAExtractor` | knowledge_cleaning/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/knowledge_cleaning/generate/qa_extract.py) |
| `PromptedVQAGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/core_vision/generate/prompted_vqa_generator.py) |
| `LLMOutputParser` | pdf2vqa/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/pdf2vqa/generate/llm_output_parser.py) |
| `MinerU2LLMInputOperator` | pdf2vqa/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/pdf2vqa/generate/mineru_to_llm_input_operator.py) |
| `PDF_Merger` | pdf2vqa/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/pdf2vqa/generate/pdf_merger.py) |
| `QA_Merger` | pdf2vqa/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/pdf2vqa/generate/qa_merger.py) |
| `VQAFormatter` | pdf2vqa/generate | 是 | [文件](../../repos/dataflow/dataflow/operators/pdf2vqa/generate/vqa_formatter.py) |

### 相关 Pipeline（包括仅供后续参考的高级流程）

| 类 | 实际 run 调用数 | 源码 |
| --- | --- | --- |
| `KBCleaningPDF_APIPipeline` | 4 | [文件](../../repos/dataflow/dataflow/statics/pipelines/api_pipelines/kbcleaning_pipeline.py) |
| `PDF_VQA_extract_optimized_pipeline` | 7 | [文件](../../repos/dataflow/dataflow/statics/pipelines/api_pipelines/pdf_vqa_extract_pipeline.py) |
| `Text2QA_APIPipeline` | 3 | [文件](../../repos/dataflow/dataflow/statics/pipelines/api_pipelines/text2qa_pipeline.py) |
| `TextSFTSynthesis_APIPipeline` | 3 | [文件](../../repos/dataflow/dataflow/statics/pipelines/api_pipelines/text_sft_synthesis_pipeline.py) |
| `KBCleaning_CPUPipeline` | 2 | [文件](../../repos/dataflow/dataflow/statics/pipelines/cpu_pipelines/kbcleaning_pipeline_url.py) |
| `SFTTextFilter_CPUPipeline` | 1 | [文件](../../repos/dataflow/dataflow/statics/pipelines/cpu_pipelines/text_sft_filter.py) |
| `KBCleaning_PDFSglang_GPUPipeline` | 5 | [文件](../../repos/dataflow/dataflow/statics/pipelines/gpu_pipelines/kbcleaning/kbcleaning_pipeline_sglang.py) |
| `KBCleaning_PDFvllm_GPUPipeline` | 5 | [文件](../../repos/dataflow/dataflow/statics/pipelines/gpu_pipelines/kbcleaning/kbcleaning_pipeline_vllm.py) |
| `SFTTextFilter_GPUPipeline` | 3 | [文件](../../repos/dataflow/dataflow/statics/pipelines/gpu_pipelines/text_sft_filter.py) |
| `SFTTextSynthetic_GPUPipeline` | 29 | [文件](../../repos/dataflow/dataflow/statics/pipelines/gpu_pipelines/text_sft_synthetic.py) |

## mm：`155253460f6f2e50705a3e779f259b382a382822`

### 算子

| 类 | 类别/步骤 | 父模块惰性导出 | 源码 |
| --- | --- | --- | --- |
| `GeneralTextAnswerEvaluator` | core_vision/eval | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/eval/general_text_answer_evaluator.py) |
| `EvalImageGenerationGenerator` | core_vision/image | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/eval/image/image_evaluator.py) |
| `ImageCLIPEvaluator` | core_vision/eval | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/eval/image_clip_evaluator.py) |
| `ImageLongCLIPEvaluator` | core_vision/eval | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/eval/image_longclip_evaluator.py) |
| `ImageVQAScoreEvaluator` | core_vision/eval | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/eval/image_vqascore_evaluator.py) |
| `VideoAestheticEvaluator` | core_vision/eval | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/eval/video_aesthetic_evaluator.py) |
| `VideoLuminanceEvaluator` | core_vision/eval | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/eval/video_luminance_evaluator.py) |
| `VideoOCREvaluator` | core_vision/eval | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/eval/video_ocr_evaluator.py) |
| `CatFilter` | core_vision/filter | 否 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/cat_filter.py) |
| `CLIPScoreFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/clipscore_filter.py) |
| `DataTailorFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/datatailor_filter.py) |
| `FailRateFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/failrate_filter.py) |
| `ImageAestheticFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_aesthetic_filter.py) |
| `ImageCatFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_cat_filter.py) |
| `ImageClipFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_clip_filter.py) |
| `ImageComplexityFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_complexity_filter.py) |
| `ImageConsistencyFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_consistency_filter.py) |
| `ImageDeduplicateFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_deduplication_filter.py) |
| `TextDuplicateFilter` | core_vision/filter | 否 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_diversity_filter.py) |
| `ImageDuplicateFilter` | core_vision/filter | 否 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_diversity_filter.py) |
| `ImageDiversityFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_diversity_filter.py) |
| `ImageSensitiveFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/image_sensitive_filter.py) |
| `KNNSimilarityFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/knn_similarity_filter.py) |
| `RuleBaseFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/rule_base_filter.py) |
| `ScoreFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/score_filter.py) |
| `VideoAestheticFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_aesthetic_filter.py) |
| `VideoClipFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_clip_filter.py) |
| `VideoFrameFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_frame_filter.py) |
| `VideoInfoFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_info_filter.py) |
| `VideoLuminanceFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_luminance_filter.py) |
| `VideoMotionScoreFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_motion_score_filter.py) |
| `VideoOCRFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_ocr_filter.py) |
| `VideoResolutionFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_resolution_filter.py) |
| `VideoSceneFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_scene_filter.py) |
| `VideoScoreFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/video_score_filter.py) |
| `VisionDependentFilter` | core_vision/filter | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/filter/vision_dependent_filter.py) |
| `BatchVQAGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/batch_vqa_generator.py) |
| `FixPromptedVQAGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/fix_prompted_vqa_generator.py) |
| `ImageBboxGenerator` | core_vision/generate | 否 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/image_bbox_generator.py) |
| `MultimodalMathGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/multimodal_math_generator.py) |
| `PersQAGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/personalized_qa_generator.py) |
| `PromptTemplatedVQAGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/prompt_templated_vqa_generator.py) |
| `PromptedImageEditGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/prompted_image_edit_generator.py) |
| `PromptedImageGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/prompted_image_generator.py) |
| `PromptedVQAGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/prompted_vqa_generator.py) |
| `VideoToCaptionGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/video_caption_generator.py) |
| `VideoClipGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/video_clip_generator.py) |
| `VideoCOTQAGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/video_cotqa_generator.py) |
| `VideoMergedCaptionGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/video_merged_caption_generator.py) |
| `VideoCaptionToQAGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/video_qa_generator.py) |
| `VisualReasoningGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/visual_reasoning_generator.py) |
| `VLMBBoxGenerator` | core_vision/generate | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/generate/vlm_bbox_generator.py) |
| `VisionSegCutoutRefiner` | core_vision/refine | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/refine/vision_seg_cutout_refiner.py) |
| `VisualDependencyRefiner` | core_vision/refine | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/refine/visual_dependency_refiner.py) |
| `VisualGroundingRefiner` | core_vision/refine | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/refine/visual_grounding_refiner.py) |
| `WikiQARefiner` | core_vision/refine | 是 | [文件](../../repos/dataflow-mm/dataflow/operators/core_vision/refine/wiki_qa_refiner.py) |

### 相关 Pipeline（包括仅供后续参考的高级流程）

| 类 | 实际 run 调用数 | 源码 |
| --- | --- | --- |
| `ImageCaptionPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/image_caption.py) |
| `ContextVQAPipeline` | 2 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/image_contextvqa.py) |
| `ImageEditingAPIPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/image_editing_api_pipeline.py) |
| `ImageGCoTPipeline` | 5 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/image_gcot_api_pipeline.py) |
| `ImageRegionCaptionPipeline` | 2 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/image_region_caption_api_pipeline.py) |
| `ImageScaleCaptionPipeline` | 11 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/image_scale_caption_api_pipeline.py) |
| `VisualOnlyMCQPipeline` | 3 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/image_visual_only_mcq_api_pipeline.py) |
| `ImageVQAPipeline` | 2 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/image_vqa.py) |
| `ImageGenerationAPIPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/text_to_image_generation_api_pipeline.py) |
| `VisionMCTSReasoningPipeline` | 2 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/api_pipelines/vision_mct_reasoning_api_pipeline.py) |
| `ImageAestheticFilterPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/cpu_pipelines/image_filter_aesthetic.py) |
| `ImageDiversityFilterPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/cpu_pipelines/image_filter_diversity.py) |
| `ContextVQAPipeline` | 2 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/context_vqa.py) |
| `ImageCaptioningPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image2caption.py) |
| `ImageQAPipeline` | 2 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image2qa.py) |
| `ImageGenerationPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_editing_pipeline.py) |
| `ClipEvalPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_eval_clip.py) |
| `LongClipEvalPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_eval_longclip.py) |
| `VQAScoreEvalPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_eval_vqascore.py) |
| `ImageCatFilterPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_filter_cat.py) |
| `ImageClipFilterPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_filter_clip.py) |
| `ComplexityFilterPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_filter_complexity.py) |
| `ImageConsistencyFilterPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_filter_consistency.py) |
| `ImageDeduplicateFilterPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_filter_deduplicate.py) |
| `ImageSensitiveFilterPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_filter_sensitive.py) |
| `ImageGCoTPipeline` | 5 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_gcot_pipeline.py) |
| `ImageRegionCaptionPipeline` | 2 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_region_caption_pipeline.py) |
| `ImageScaleCaptionPipeline` | 11 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_scale_caption_pipeline.py) |
| `VisualOnlyMCQPipeline` | 3 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/image_visual_only_mcq_pipeline.py) |
| `ImageGenerationPipeline` | 1 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/text_to_image_generation_pipeline.py) |
| `VisionMCTSReasoningPipeline` | 2 | [文件](../../repos/dataflow-mm/dataflow/statics/pipelines/gpu_pipelines/vision_mct_reasoning_pipeline.py) |
