"""Render verified common-protocol results as Markdown and a numeric CSV."""
import argparse
import csv
import json
from pathlib import Path

STRATEGIES={'G00':'普通静态 SFT','G01':'随机选择','G02':'Loss(high) 选择','G03':'Delta-loss 选择',
            'G04':'固定比例混合','G05':'ODM 动态配比','G06':'Uniform 等权','G07':'Loss-linupper 加权'}


def values(ev):
    m=ev['metrics']
    return [m['scicite_classification']['accuracy'],m['scicite_classification']['macro_f1'],
            m['genia_ner']['entity_exact_micro_f1'],m['genia_ner']['json_success'],
            m['bioasq_factoid_qa']['em'],m['bioasq_factoid_qa']['token_f1'],m['scitldr_aic']['rouge_l_f1']]


def render(summary_path,report_path,csv_path):
    s=json.loads(summary_path.read_text())
    assert s['status']=='UNIFORM_PROTOCOL_CORE8_COMPLETE_WITH_REPRODUCIBILITY_LIMITATION'
    assert s['completed_predictions']==576 and s['completed_core_optimizer_updates']==192
    names=['BASE']+list(STRATEGIES)
    with csv_path.open('w',newline='') as handle:
        writer=csv.writer(handle)
        writer.writerow(['model','strategy','training_origin','evaluation_n','classification_accuracy_pct',
            'classification_macro_f1_pct','ner_micro_f1_pct','ner_json_success_pct','qa_em_pct','qa_f1_pct',
            'summary_rouge_l_pct','cap_hits','empty_outputs','reasoning_tag_outputs'])
        for name in names:
            e=s['evaluations'][name]
            writer.writerow([name,STRATEGIES.get(name,'未微调原模型'),'reused_verified_pair' if name in s['reused_runs'] else 'new',64]+
                [100*x for x in values(e)]+[e['cap_hits'],e['empty_outputs'],e['reasoning_tag_outputs']])
    lines=['# 统一数值设置后的八组策略对比','',
        '**G00–G05 各 24 步训练及原模型和这六个 adapter 的重载评测已完成。** G06/G07 复用此前同协议且严格配对验收通过的结果。八组共 192 次更新，原模型加八个 adapter 共 576 条冻结预测；本次实际新增 144 次更新、448 条预测。','',
        '机器证据：[uniform-results-summary.json](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/uniform-core8/uniform-results-summary.json)。数值表：[results.csv](../../deploy/plans/dataflex-strategy-20261023/evidence-20261023/uniform-core8/results.csv)。旧轮次与失败尝试保留，不能把本轮描述为八组都重新训练了一次。','',
        '## 共同条件与比较范围','',
        '- 数值协议均为 `torch-math-cublas4096-v2`：math-SDPA、PyTorch deterministic algorithms、cuDNN deterministic=true/benchmark=false、cuBLAS workspace=:4096:8；CUDA_LAUNCH_BLOCKING 未设置。HF 的 full_determinism=false 用于防止其覆盖 workspace，实际确定性算法开关为 true。',
        '- 八组共用同一初始 adapter；全部初始参数、量化状态和缓冲区 3,049 项哈希一致。模型 revision、NF4/BF16、LoRA r16/alpha32/dropout0.05、优化器、LR、种子、长度上限和数据等 46 个共同配置字段一致。',
        '- 同一冻结 256 train / 32 validation / 64 test；四任务各 16 条测试。每组 24 次更新、96 次样本展示、有效 batch=4。数据与测试分母未重抽或按分数调整。',
        '- **微批并非八组完全相同**：G00–G05 是微批1/累积4，G06/G07 是微批2/累积2。当前 ODM 不支持混域微批，非均匀加权又要求微批至少2。G00–G05 可在同批配置下比较，G06/G07 是另一组受控配对；跨组比较仍包含该实现差别。',
        '- 策略改变实际采样、重复次数、来源分布和训练 token 数；本轮等更新/样本展示预算，**不是等 token 或等 FLOP 比较**。额外选择评分开销单列。',
        '- 九个模型均采用相同原生非思考生成模板、greedy、max_new_tokens=256、同一评分脚本和冻结参考答案。完整预测 SHA、adapter SHA、数据 SHA 和脚本身份已核对。','',
        '方法语义保持原实现：Loss(high) 为分组概率抽样而非严格 top-k；ODM 以此前一微批返回的、经累积缩放的 loss 作反馈，不是整个窗口平均回报；两样本 linupper 的 min-max 归一化使非等 loss 批次的权重约为 [0.269,0.731]（顺序依 loss）。这些差别属于本次实际验证的策略实现。','',
        '**残余限制：**额外对照发现，G01/G02 在首次选择前，已记录的微批1 token 身份、监督边界、初始参数及 RNG 控制相同，仍存在数值差异；未记录的输入/运行状态差别尚未完全排除。因此这轮已统一指定的数值设置，但不能称全部策略的训练轨迹已位级可复现；分数差异不能严格全部归因于策略。G06/G07 的微批2配对通过结论继续成立。具体原始梯度比较和原容差失败计数保存在机器汇总的 `preselection_numerical_diagnostic`。','',
        '## 最新冻结评测结果','',
        '以下均为百分制，越高越好。NER JSON 有效率表示格式可解析，不等于实体预测正确。未把不同任务简单平均成总分。','',
        '| 模型 | 策略 | 分类 Acc / Macro-F1 | NER F1 / JSON | QA EM / F1 | 摘要 ROUGE-L | cap / 空答 / think |',
        '|---|---|---:|---:|---:|---:|---:|']
    diagnostic=s['preselection_numerical_diagnostic']
    first_B=next(r for r in diagnostic['representative_raw_gradient_comparisons'] if r['micro']==1 and r['part']=='B')
    diagnostic_note='预热对照的 32 对代表性梯度范数中，%d 对超过原 atol=1e-4 / rtol=0.02，最大范数相对差 %.2f%%（含首个数值分歧传播后的更新）；首微批 LoRA B 完整梯度相对 L2 差 %.2f%%。该差异未通过放宽容差消除。'%(diagnostic['warmup_norm_pairs_outside_original_tolerance'],100*diagnostic['warmup_max_norm_relative_difference'],100*first_B['relative_l2_difference'])
    index=lines.index('## 最新冻结评测结果')
    lines[index:index]=[diagnostic_note,'']
    for name in names:
        e=s['evaluations'][name];v=[100*x for x in values(e)]
        lines.append('| %s | %s | %.2f / %.2f | %.2f / %.2f | %.2f / %.2f | %.2f | %d / %d / %d |'%(
            name,STRATEGIES.get(name,'未微调原模型'),*v,e['cap_hits'],e['empty_outputs'],e['reasoning_tag_outputs']))
    lines+=['','## 观察与限制','',
        '这些是单种子、24 步、每任务 16 条测试的实际观察。分类 Acc、QA EM、JSON 有效率等比例指标多一题即变化 6.25 个百分点，不能据此给算法统计排名。分类多数类 Background 占 13/16，恒猜多数类的 Acc 已有 81.25%，需同时看 Macro-F1。NER 的一条参考本身长于 256 生成预算；cap、空答、解析失败没有从分母删掉。QA 只用公开单条参考；摘要 ROUGE-L 不验证事实可靠性。', '',
        '本轮验证共同数值协议生效及真实训练/重载，同时记录了微批1预热的残余数值差异；不宣称每个新策略都已做第二次独立重复训练。G06/G07 的严格梯度配对结论有其独立 receipt。原始文档 ID 缺失导致同论文不同上下文无交叉仍不能证明。','',
        '| G07 相对 G06（同微批、同初始状态的配对） | 百分点变化 |','|---|---:|']
    a=values(s['evaluations']['G06']);b=values(s['evaluations']['G07'])
    for label,x,y in zip(['分类 Acc','分类 Macro-F1','NER F1','NER JSON','QA EM','QA F1','摘要 ROUGE-L'],a,b):
        lines.append('| %s | %+.2f |'%(label,100*(y-x)))
    lines+=['','## 真实训练消费与开销','',
        'CLI 秒包括加载、观察、训练、评分、保存和验证；scoring 是其子集，不再次相加。G06/G07 数字来自已验收的同协议配对，不计为本次新增开销。GPU 与其他任务共享，这些时间是本次观察，不是独占卡性能保证。','',
        '| 组 | 本次新训/复用 | 微批×累积 | 不同样本 / 展示 | 有效 / 监督 token | CLI / scoring 秒 | allocated / reserved GiB |',
        '|---|---|---:|---:|---:|---:|---:|']
    for name in STRATEGIES:
        run=s['core_runs'][name];r=run['resource'];batch=s['batch_settings'][name]
        lines.append('| %s | %s | %d×%d | %d / %d | %d / %d | %.1f / %.1f | %.3f / %.3f |'%(
            name,'复用' if name in s['reused_runs'] else '新训',batch['microbatch'],batch['accumulation'],
            run['distinct_samples'],run['sample_presentations'],run['effective_tokens'],run['supervised_tokens'],
            r['seconds'],run['scoring_seconds'],r['peak_allocated_gib'],r['peak_reserved_gib']))
    lines+=['','## 留存与复核','',
        '学校结果根目录：`/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023/uniform-core8-20261023`。G06/G07 通过相对链接复用 `gradient-resolution-v2-20261023` 的训练与评测，计划同时绑定其 verdict/summary 哈希；未移动或覆盖原件。G01–G03 使用新的独立策略缓存。完整梯度、逐项初始哈希、adapter、checkpoint、全量预测留学校；Mac 留紧凑证据。', '',
        '实际新增预算为 6×24=144 次更新和 7×64=448 条预测。加此前全部诊断、失败与门测，累计 511 次更新、1,160 条生成记录；其中同协议对比本身为 192 次更新和 576 条预测，不能重复计入新增预算。', '',
        'Mac 28 项 CPU 回归中 27 通过、1 PEFT 跳过；学校 28 项全部通过。全部八组实际 DataFlex 库源码/配置共 75 文件一致，安装与平台副本另核对。平台 SSH 训练执行器、P2/P3 未在此轮执行。','']
    report_path.write_text('\n'.join(lines))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--csv',type=Path,required=True)
    args=parser.parse_args();render(args.summary,args.report,args.csv)
