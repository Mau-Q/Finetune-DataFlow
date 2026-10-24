"""Verify the fresh cohort and derive effect/cost tables without model calls."""
import argparse
import json
from pathlib import Path
import yaml
from observed_run import sha
from extended_execution_policy import PROTOCOL
from summarize_results import summarize, read_rows
from summarize_uniform_core8 import COMMON_KEYS

NAMES = ['BASE']+['G%02d'%i for i in range(8)]
LABELS = ['static', 'random select', 'loss(high) select', 'delta loss select',
          'static mix', 'ODM mix', 'uniform weight', 'loss linupper']


def verify(root):
    result = summarize(root)
    plan = json.loads((root/'cohort-plan.json').read_text())
    assert plan['reused_runs'] == [] and len(plan['runs']) == 8
    assert plan['new_optimizer_updates'] == 192 and plan['new_predictions'] == 576
    gates = json.loads((root.parent/'gpu1-gates-20261024/gate-verdict.json').read_text())
    assert gates['status'] == 'GPU1_CAPACITY_RELOAD_AND_REPEATABILITY_PASS'
    bootstrap = json.loads((root.parent/'gpu1-gates-20261024/bootstrap-order-detail.json').read_text())
    assert bootstrap['status'] == 'TORCH_CUBLAS_POLICY_PRECEDES_CONTEXT_FLA_PINNING_PRECEDES_MODEL'
    gate_reload_costs = {}
    for name in ['GATE2-B1', 'GATE2-B2']:
        directory = root.parent/'gpu1-gates-20261024/evaluation'/name
        receipt = json.loads((directory/'metrics.json').read_text())
        predictions = read_rows(directory/'predictions.jsonl')
        assert receipt['n'] == len(predictions) == 2
        gate_reload_costs[name] = dict(receipt, prompt_tokens=sum(r['prompt_tokens'] for r in predictions),
                                      generated_tokens=sum(r['generated_tokens'] for r in predictions))
    initial, identities, policies = [], [], []
    settings = {}
    for name in NAMES[1:]:
        folder = root/name/'attempt1'
        config = yaml.safe_load((folder/'actual-config.yaml').read_text())
        resource = json.loads((folder/'resource.json').read_text())
        manifest = json.loads((folder/'manifest.json').read_text())
        audit = result['core_runs'][name]
        assert resource['config_sha256'] == sha(folder/'actual-config.yaml') == sha(root/name/'train.yaml')
        assert manifest['components_sha256'] == sha(Path(config['components_cfg_file']))
        assert manifest['observer_sha256'] == sha(Path(__file__).with_name('observed_run.py'))
        assert all(sha(folder/f) == expected for f, expected in audit['observation_sha256'].items())
        assert config['max_steps'] == 24 and config['cutoff_len'] == 1024 and config['lora_dropout'] == .05
        assert config['per_device_train_batch_size']*config['gradient_accumulation_steps'] == 4
        pair = json.loads((folder/'paired-control-receipt.json').read_text())
        assert pair['deterministic_execution_requested'] == PROTOCOL
        assert pair['initial_adapter_tensor_sha256'] == plan['initial_adapter_tensor_sha256']
        assert pair['snapshot_sha256'] == plan['snapshot_sha256']
        assert pair['micro_rng_seed_base'] == 420000
        assert pair['sdp_backends'] == {'flash': False, 'math': True, 'mem_efficient': False, 'cudnn': False}
        assert pair['cublas_workspace_config'] == ':4096:8' and pair['cuda_launch_blocking'] is None
        initial.append(json.loads((folder/'initial-model-hashes.json').read_text()))
        identities.append(json.loads((folder/'manifest.json').read_text()))
        policies.append(json.loads((folder/'fla-policy.json').read_text()))
        run = result['core_runs'][name]
        run['scoring_samples'] = sum(len(r['positions']) for r in read_rows(folder/'scores.jsonl')) if (folder/'scores.jsonl').exists() else 0
        run['fla_compilation_candidates'] = len(json.loads((folder/'fla-compile-configs.json').read_text()))
        run['batch'] = {'microbatch': config['per_device_train_batch_size'], 'accumulation': config['gradient_accumulation_steps']}
        settings[name] = {k: config.get(k) for k in COMMON_KEYS}
    assert all(x == initial[0] for x in initial) and len(initial[0]) == 3049
    assert all(x == settings['G00'] for x in settings.values()), settings
    for identity in identities:
        assert len(identity['source_files']) == 75
        for key in ['source_files', 'packages', 'observer_sha256', 'model_config_sha256', 'dataset_info_sha256']:
            assert identity[key] == identities[0][key], key
    assert all(p == policies[0] for p in policies)
    common = {}
    for left, right, micros in [('G01', 'G02', 16), ('G06', 'G07', 8)]:
        a, b = [root/n/'attempt1' for n in [left, right]]
        checks = {f: read_rows(a/f)[:micros] == read_rows(b/f)[:micros]
                  for f in ['consumption.jsonl', 'paired-rng.jsonl', 'loss.jsonl']}
        checks['optimizer_gradients_first4'] = read_rows(a/'optimizer-gradients.jsonl')[:4] == read_rows(b/'optimizer-gradients.jsonl')[:4]
        checks['raw_representative_gradients'] = all(sha(p) == sha(b/p.name) for p in a.glob('gradient-*.safetensors'))
        assert all(checks.values()), (left, right, checks)
        common[left+'__'+right] = checks
    for name in NAMES:
        ev = result['evaluations'][name]
        protocol = ev['execution_protocol']
        assert protocol['deterministic_execution'] == PROTOCOL and protocol['deterministic_algorithms']
        assert protocol['sdp_backends'] == {'flash': False, 'math': True, 'mem_efficient': False, 'cudnn': False}
        assert protocol['wrapper_sha256'] == sha(Path(__file__).with_name('gpu1_entry.py'))
        assert protocol['observer_sha256'] == identities[0]['observer_sha256']
        assert ev['model_config_sha256'] == identities[0]['model_config_sha256']
        assert json.loads((root/'evaluation'/name/'fla-policy.json').read_text()) == policies[0]
        assert ev['evaluation_script_sha256'] == sha(Path(__file__).with_name('evaluate_frozen.py'))
        assert ev['generation'] == {'prompt_method': 'hf_native_chat_template_enable_thinking_false',
            'do_sample': False, 'max_new_tokens': 256, 'template': 'qwen3_5_nothink', 'enable_thinking': False}
    result.update(status='GPU1_FRESH_CORE8_AND_NINE_MODEL_EVALUATION_VERIFIED', scope='Fresh actual GPU1 direct DataFlex CLI cohort; single seed descriptive comparison',
                  artifact_root_container=str(root),
                  artifact_root='/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/'+str(root.relative_to('/runs')),
                  protocol=PROTOCOL, initial_model_state_entries_equal=3049, common_training_settings=settings['G00'],
                  first_four_update_comparisons=common, gate_verdict_sha256=sha(root.parent/'gpu1-gates-20261024/gate-verdict.json'),
                  gate_costs=gates['attempt_costs'], gate_capacity=gates['capacity'],
                  gate_reload_costs=gate_reload_costs,
                  gate_scoring_probe=json.loads((root.parent/'gpu1-gates-20261024/evaluation/GATE2-B2/score-batch-check.json').read_text()),
                  bootstrap_order=bootstrap,
                  new_core_optimizer_updates=192, new_core_predictions=576, new_gate_optimizer_updates=28, new_gate_predictions=4,
                  cumulative_observed_optimizer_updates=732, cumulative_generated_rows_including_gates=1292,
                  batch_scope=plan['batch_scope'], new_training_runs=plan['runs'], reused_runs=[],
                  initial_adapter_tensor_sha256=plan['initial_adapter_tensor_sha256'],
                  source_script_sha256={p.name: sha(p) for p in Path(__file__).parent.glob('*.py')})
    result['delta_vs_base'] = {}
    primary = [('scicite_classification', 'accuracy'), ('scicite_classification', 'macro_f1'),
               ('genia_ner', 'entity_exact_macro_sample_f1'), ('genia_ner', 'entity_exact_micro_f1'),
               ('bioasq_factoid_qa', 'em'), ('bioasq_factoid_qa', 'token_f1'), ('scitldr_aic', 'rouge_l_f1')]
    for name in NAMES[1:]:
        result['delta_vs_base'][name] = {t+'.'+m: result['evaluations'][name]['metrics'][t][m]-result['evaluations']['BASE']['metrics'][t][m] for t, m in primary}
    (root/'results-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


def report(result, output):
    pct = lambda v: '%.2f'%(100*v)
    evs, runs = result['evaluations'], result['core_runs']
    def metric(name, task, key):
        value = evs[name]['metrics'][task][key]
        return pct(value) + ('' if name == 'BASE' else ' (%+.2f)'%(100*result['delta_vs_base'][name][task+'.'+key]))
    lines = ['# GPU 1：统一数值协议下的八组训练与九模型评测', '',
             '日期：2026-10-24（Asia/Shanghai）。八组均为新建目录、从共享初始 adapter 开始的 24 步训练；原模型与八个保存后重载的 adapter 各生成 64 条预测，共 576 条。', '',
             '证据等级：TOOL_OBSERVED 为真实 GPU 训练、门测、重载生成及机械审计；INFERRED 仅包括按冻结长度与完整循环数推导的验证 token 预算；NOT_RUN 包括多种子稳定性、长期训练效果、平台 SSH 执行器及 P2/P3。', '',
             '执行状态：`'+result['status']+'`。单种子、每任务 16 个测试样本，仅作本次有限运行的描述性比较，不构成稳定的算法排名。没有合并旧协议的模型或预测。', '',
             '下表为百分数，括号为相对本轮原模型的百分点变化。SciCite 用严格标签 accuracy / macro F1；GENIA 主列为全 16 样本的实体精确匹配 sample-macro F1，JSON 失败按 0 计；BioASQ 用发布的单一答案算 EM / token F1；SciTLDR 为明确分词方式下的 ROUGE-L token F1。', '',
             '| 模型 / 策略 | SciCite acc / macro F1 | GENIA sample F1 | BioASQ EM / F1 | SciTLDR ROUGE-L | GENIA JSON | 截断 / 64 |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for name in NAMES:
        vals = evs[name]; met = vals['metrics']; label = '原模型' if name == 'BASE' else LABELS[int(name[1:])]
        lines.append('| '+name+' '+label+' | '+metric(name,'scicite_classification','accuracy')+' / '+metric(name,'scicite_classification','macro_f1')+' | '+metric(name,'genia_ner','entity_exact_macro_sample_f1')+' | '+metric(name,'bioasq_factoid_qa','em')+' / '+metric(name,'bioasq_factoid_qa','token_f1')+' | '+metric(name,'scitldr_aic','rouge_l_f1')+' | '+pct(met['genia_ner']['json_success'])+'% | '+str(vals['cap_hits'])+' |')
    lines += ['', 'GENIA 补充实体 micro F1（保留失败样本的漏检数；成功解析子集分数另存 JSON）：', '', '| 模型 | 实体 micro F1（Δ） | 空输出 | 无效分类标签 |', '|---|---:|---:|---:|']
    for name in NAMES:
        lines.append('| '+name+' | '+metric(name,'genia_ner','entity_exact_micro_f1')+' | '+str(evs[name]['empty_outputs'])+' | '+str(evs[name]['metrics']['scicite_classification']['invalid_labels'])+' |')
    lines += ['', '每组实际展示 96 次样本。重复率为 1−不同样本数/96；有效 token 包含输入与回答，监督 token 只计实际标签。CLI 秒包含加载、训练、选择评分、验证和保存；评分时间是 CLI 的子集，不重复相加。', '',
              '| 组 | 微批 / 累积 | 不同样本 / 重复率 | 有效 / 监督 token | 选择评分样本 / token | CLI / 评分秒 | allocated / reserved GiB |', '|---|---:|---:|---:|---:|---:|---:|']
    for name in NAMES[1:]:
        r=runs[name]; mem=r['resource']; batch=r['batch']
        lines.append('| %s | %s / %s | %d / %.1f%% | %d / %d | %d / %d | %.1f / %.1f | %.3f / %.3f |'%(name,batch['microbatch'],batch['accumulation'],r['distinct_samples'],100*r['repetition_fraction'],r['effective_tokens'],r['supervised_tokens'],r['scoring_samples'],r.get('scoring_effective_tokens',0),mem['seconds'],r['scoring_seconds'],mem['peak_allocated_gib'],mem['peak_reserved_gib']))
    lines += ['', '九模型生成成本（原模型没有本轮训练成本）：', '', '| 模型 | prompt / 生成 token | 总秒 | allocated / reserved GiB |', '|---|---:|---:|---:|']
    for name in NAMES:
        e=evs[name]
        lines.append('| %s | %d / %d | %.1f | %.3f / %.3f |'%(name,e['prompt_tokens'],e['generated_tokens'],e['total_seconds'],e['peak_allocated_gib'],e['peak_reserved_gib']))
    lines += ['', '额外门测成本：', '', '| 门测 | 更新 / 展示 | 有效 / 监督 token | CLI 秒 | allocated / reserved GiB |', '|---|---:|---:|---:|---:|']
    for name, cost in result['gate_costs'].items():
        lines.append('| %s | %d / %d | %d / %d | %.1f | %.3f / %.3f |'%(name,cost['optimizer_updates'],cost['sample_presentations'],cost['effective_tokens'],cost['supervised_tokens'],cost['seconds'],cost['peak_allocated_gib'],cost['peak_reserved_gib']))
    lines += ['', '`P-*` 为保留 max_steps=24、在第 4 次更新后主动终止的复现探针。原始 resource.json 的 FAIL 是通用 runner 的未完成状态；probe-complete.json 记录主动终止边界，门测验收另核对输入、梯度及更新后参数哈希。六个探针均计入额外预算。']
    lines += ['', '两次门测重载生成成本：', '', '| 门测 | 预测数 | prompt / 生成 token | 总秒 | allocated / reserved GiB |', '|---|---:|---:|---:|---:|']
    for name, cost in result['gate_reload_costs'].items():
        lines.append('| %s | %d | %d / %d | %.1f | %.3f / %.3f |'%(name,cost['n'],cost['prompt_tokens'],cost['generated_tokens'],cost['total_seconds'],cost['peak_allocated_gib'],cost['peak_reserved_gib']))
    probe = result['gate_scoring_probe']
    lines += ['', 'B2 重载进程另含评分 batch1/2 一致性检查：%d 次样本前向、%d 个完整 token，loss 最大差 %.8f，原容差 atol=0.03、rtol=0.01。其耗时已包含在该重载进程总秒数中。另做两次零更新、零预测的启动顺序检查。'%(probe['forward_samples'],probe['forward_full_tokens'],probe['max_abs_difference'])]
    lines += ['', '正式训练 CLI 累计 %.1f 秒（其中选择评分 %.1f 秒），九模型生成累计 %.1f 秒。各组验证共完整循环 %s 次，验证 token 预算按冻结长度与循环数推导，详见汇总 JSON，未与逐微批直接观测量混为同一证据。'%(result['core_cli_seconds'],result['scoring_seconds_included_in_cli'],result['evaluation_seconds'], '/'.join(str(runs[n]['validation_complete_loops_including_final']) for n in NAMES[1:])), '',
              '本轮正式训练共 192 次更新、768 次样本展示；额外门测 28 次更新、112 次展示、4 条重载预测。正式预测 576 条。结合交接中的历史预算，累计观察到 732 次更新、1292 条生成记录。两次准备阶段失败均发生于模型调用之前，不计训练预算。', '',
              'GPU 1 独立容器按 UUID `GPU-492f7b9f-5be1-64c0-58eb-9d3d582fcddc` 绑定，network=none，复用原模型只读挂载。迁移核对 75 个 DataFlex 源文件与关键依赖，未停止旧 GPU 2/GPU 3 容器或其他服务。显存与其他服务共享，逐阶段检查余量；时间反映本次共享机器上的实际经历。', '',
              '统一协议为 `'+PROTOCOL+'`。实际启动顺序经独立零更新检查：PyTorch/cuBLAS 控制先于 CUDA 上下文初始化；FLA 导入时建立上下文，固定配置随后完成，早于 CUDA 分配器配置、模型加载与训练/生成计算。不能将其表述为全部 FLA 配置都在任何 CUDA 上下文建立之前完成。保留 BF16/NF4、LoRA dropout 0.05、共享初始 adapter 和每微批 RNG 控制；固定 FLA 前向/反向配置选择并检查已知源码哈希。microbatch1/2 的容量、保存重载、评分一致性与独立进程四步复现均已通过。正式 G01/G02、G06/G07 的前四次更新梯度哈希亦核验相同。复现结论限当前模型、数据、硬件和软件栈。', '',
              'G00–G05 为 microbatch1/accumulation4，G06/G07 为 microbatch2/accumulation2，有效 batch 均为 4。不同微批不是逐位等价的计算；不把跨家族差异全部归因于策略。ODM 保留实际“上一微批经累积缩放的 loss”反馈；两样本 linupper 的权重幅度受 min-max 归一化限制。', '',
              '数据仍为冻结的 SciRIFF 256 train / 32 validation / 64 test，完整训练序列 ≤1024。测试 ID、参考答案和分母逐模型核对；测试不反馈到选择或配比。生成统一采用原生非思考模板、greedy、max_new_tokens=256，截断与 JSON 失败保留。未构造跨任务总分。BioASQ 属 SciRIFF qa.abstractive，替代原计划中可用样本不足的短答案任务；源数据缺原文档 ID，不能证明同论文不同上下文完全无交叉。', '',
              '完整 adapter、预测与逐步诊断留在学校服务器：`'+result['artifact_root']+'`。Mac 仅保存紧凑报告、汇总与哈希证据。平台 SSH 执行器、P2/P3、长期效果与多种子稳定性不在本轮验收范围。', '']
    output.write_text('\n'.join(lines))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root', type=Path, required=True);parser.add_argument('--report', type=Path, required=True)
    args=parser.parse_args();result=verify(args.root);report(result,args.report)
    print(json.dumps({'status': result['status'], 'updates': 192, 'predictions': 576}), flush=True)
