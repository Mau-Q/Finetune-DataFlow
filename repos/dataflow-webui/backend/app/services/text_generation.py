"""Wizard/canvas share PipelineRegistry; execution keeps the native batch boundary."""
import copy
import json
import os
import uuid
from pathlib import Path
from app.core.container import container
from app.core.config import settings
from app.services.data_library import LibraryError, _hash, _json_bytes, _now
from app.services.resource_resolution import resolve_pipeline_resources
from app.services.task_store import patch_task


def template():
    rec = json.loads((Path(__file__).parent.parent / 'templates/paper_sft13.json').read_text('utf-8'))
    workspace = Path(__file__).resolve().parents[5]
    defaults = {'mineru_script': str(workspace / 'scripts/mineru.sh'),
                'tokenizer_path': str(workspace / 'models/tokenizers/Qwen2.5-7B-Instruct'),
                'output_dir': str(Path(settings.CACHE_DIR) / 'platform-parsing')}
    for op in rec['config']['operators']:
        for param in op['params']['init']:
            if param['name'] in defaults:
                param['value'] = defaults[param['name']]
    for op in rec['config']['operators']:
        for param in op['params']['init']:
            if param['name'] == 'llm_serving':
                param['value'] = None
    rec['id'] = 'paper-sft13'
    return rec


def serving_parameters(info):
    return {p['name']: p.get('value') if p.get('value') is not None else p.get('default_value') for p in info.get('params', [])}


class TextGeneration:
    def __init__(self, app_container=None):
        self.c = app_container or container

    def save(self, name, config, pipeline_id=None):
        config = copy.deepcopy(config)
        # Snapshots belong to tasks; never persist a previous execution's input override.
        for op in config.get('operators', []):
            for param in op.get('params', {}).get('init', []):
                if param['name'] == 'llm_serving' and not param.get('value'):
                    param['value'] = None
        options = config.setdefault('execution_options', {})
        options.pop('input_snapshot', None)
        options.pop('source_identity', None)
        options.pop('serving_snapshots', None)
        retries = options.get('additional_retries', 0)
        if type(retries) is not int or not 0 <= retries <= 5:
            raise LibraryError('额外重试次数必须为 0–5 的整数')
        options.update(additional_retries=retries, max_attempts=retries+1, capture_responses=True, training_output=True, progress_unit='batch')
        body = {'name': name.strip(), 'config': config, 'tags': ['platform-text', 'sft']}
        if not body['name']:
            raise LibraryError('请填写配置名称')
        try:
            if pipeline_id:
                old = self.c.pipeline_registry.get_pipeline(pipeline_id)
                if not old or 'platform-text' not in old.get('tags', []):
                    raise LibraryError('只能从向导更新平台文本配置', 409)
                return self.c.pipeline_registry.update_pipeline(pipeline_id, body)
            return self.c.pipeline_registry.create_pipeline(body)
        except ValueError as exc:
            raise LibraryError(str(exc)) from exc

    def preflight(self, config):
        errors = []
        simple = config.get('execution_options', {}).get('simple_training')
        retries = config.get('execution_options', {}).get('additional_retries', 0)
        if type(retries) is not int or not 0 <= retries <= 5:
            errors.append('额外重试次数必须为 0–5 的整数')
        serving_snapshots = {}
        representative = config.get('execution_options', {}).get('representative_training')
        expected = ([('FormatStrPromptedGenerator' if simple.get('modality') == 'text' else 'APIImagePairGenerator'), 'TrainingPairFormatter']
                    if simple else [op['name'] for op in template()['config']['operators']])
        if config.get('execution_options', {}).get('paper_multitask_low_cost'):
            from app.services.paper_multitask import definition
            expected = [op['name'] for op in definition()['config']['operators']]
        if representative and simple:
            from app.services.representative_training import definitions
            definition = next((d for d in definitions() if d['config']['execution_options']['simple_training'] == simple), None)
            expected = [op['name'] for op in definition['config']['operators']] if definition else []
        if [op['name'] for op in config.get('operators', [])] != expected:
            errors.append('代表性流程步骤顺序不完整，请从对应模板重新检查' if representative else '最简入口需要生成、训练整理两步顺序' if simple else '文本入口需要完整的既有 13 步顺序；请在画布检查配置')
        if simple:
            if simple.get('modality') not in {'text', 'image_text'} or simple.get('training_type') not in {'sft', 'dpo'}:
                errors.append('最简 pipeline 模态或训练类型无效')
            formatter = next((op for op in config.get('operators', []) if op['name'] == 'TrainingPairFormatter'), None)
            if formatter:
                values = {p['name']: p.get('value', p.get('default_value')) for p in formatter['params']['init']}
                if any(values.get(k) != simple.get(k) for k in ('modality', 'training_type')):
                    errors.append('训练整理参数必须与 pipeline 的模态和训练类型一致')
            if not config.get('execution_options', {}).get('input_snapshot'):
                from app.services.simple_training import read_inputs
                try:
                    read_inputs(self.c, config)
                except (LibraryError, ValueError, OSError):
                    errors.append('输入不可用：文本需要非空 text 的 JSONL；图片需要已导入且可读取的图片材料')
        dataset_id = config.get('input_dataset')
        dataset_id = dataset_id.get('id') if isinstance(dataset_id, dict) else dataset_id
        dataset = self.c.dataset_registry.get(dataset_id)
        frozen_input = config.get('execution_options', {}).get('input_snapshot')
        if not frozen_input and (not dataset or not Path(dataset['root']).is_file()):
            errors.append('输入数据集不存在或文件已缺失')
        serving_operators = {'KBCTextCleaner', 'Text2MultiHopQAGenerator', 'Text2QASampleEvaluator', 'AlpagasusSampleEvaluator', 'FormatStrPromptedGenerator', 'APIImagePairGenerator'}
        for op in config.get('operators', []):
            init_params = op.get('params', {}).get('init', [])
            if op['name'] in serving_operators and not any(p.get('name') == 'llm_serving' for p in init_params):
                errors.append(f'{op["name"]}: 未配置文本服务')
            for param in init_params:
                name, value = param['name'], param.get('value')
                if name == 'llm_serving':
                    info = self.c.serving_registry._get(value) if value else None
                    if not info:
                        errors.append(f'{op["name"]}: 未配置文本服务')
                        continue
                    params = serving_parameters(info)
                    if info.get('cls_name') != 'APILLMServing_request' or not params.get('api_url') or not params.get('model_name'):
                        errors.append(f'{op["name"]}: 服务类型、端点或模型未配置')
                    if not params.get('api_key') and not os.environ.get(params.get('key_name_of_api_key') or ''):
                        errors.append(f'{op["name"]}: 服务密钥未配置')
                    from app.services.personal_execution import authorize, identity
                    authorize(info, identity.get())
                    safe = {k: v for k, v in params.items() if k not in {'api_key', 'key_name_of_api_key'}}
                    serving_snapshots[value] = {'id': value, 'cls_name': info['cls_name'], 'parameters': safe, 'sha256': _hash(_json_bytes(safe))}
                if name in {'mineru_script', 'tokenizer_path'} and (not value or not Path(value).exists()):
                    errors.append(f'{op["name"]}: {name} 路径不可用')
        try:
            resolve_pipeline_resources(config)
        except ValueError as exc:
            errors.append(str(exc))
        # A frozen retry must use the same non-secret serving configuration.
        frozen = config.get('execution_options', {}).get('serving_snapshots')
        if frozen and frozen != serving_snapshots:
            errors.append('服务配置已变化；请从当前配置创建新任务，不能改变旧任务的重跑条件')
        return {'ready': not errors, 'errors': errors, 'progress_unit': 'batch',
                'recovery': '完整批次复用；失败或中断批次从头重跑', 'serving_snapshots': serving_snapshots}

    def _freeze_input(self, config):
        frozen = config.get('execution_options', {}).get('input_snapshot')
        if frozen:
            for item in [frozen, *frozen['materials']]:
                path = Path(item['path'])
                if not path.is_file() or _hash(path.read_bytes()) != item['sha256']:
                    raise LibraryError('固定的输入文件已缺失或变化，不能重跑', 409)
            return frozen
        if config.get('execution_options', {}).get('simple_training'):
            from app.services.simple_training import freeze_inputs
            return freeze_inputs(self.c, config)
        dsid = config['input_dataset']
        dsid = dsid['id'] if isinstance(dsid, dict) else dsid
        record = self.c.dataset_registry.get(dsid)
        path = Path(record['root'])
        if path.suffix.lower() != '.jsonl':
            raise LibraryError('论文模板输入需要 JSONL PDF 材料清单；请通过原始数据集导入 PDF')
        try:
            rows = [json.loads(s) for s in path.read_text('utf-8').splitlines() if s.strip()]
        except (ValueError, UnicodeError) as exc:
            raise LibraryError('原始 PDF 材料清单不是有效 JSONL') from exc
        if not rows:
            raise LibraryError('原始材料清单为空')
        # Validate the whole batch before creating owned copies.
        sources = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('source'), str):
                raise LibraryError('输入清单需要 source 字段')
            if row.get('material_id'):
                source, _ = self.c.data_library.material_file(row['material_id'])
            else:
                source = Path(row['source'])
            if not source.is_file() or source.suffix.lower() != '.pdf':
                raise LibraryError('文本模板仅接受可读取的 PDF 材料')
            sources.append((source, source.read_bytes()))
        root = self.c.data_library.root / 'task_inputs' / uuid.uuid4().hex
        root.mkdir(parents=True)
        materials = []
        try:
            for index, (source, content) in enumerate(sources):
                dest = root / f'{index}.pdf'
                self.c.data_library._atomic(dest, content)
                materials.append({'path': str(dest.resolve()), 'sha256': _hash(content), 'source_name': source.name, 'material_id': rows[index].get('material_id')})
                rows[index]['source'] = str(dest.resolve())
            manifest = root / 'input.jsonl'
            content = b''.join(_json_bytes(row)+b'\n' for row in rows)
            self.c.data_library._atomic(manifest, content)
            return {'path': str(manifest.resolve()), 'sha256': _hash(content), 'materials': materials,
                    'dataset_id': dsid, 'material_count': len(rows)}
        except Exception:
            import shutil
            shutil.rmtree(root)
            raise

    async def submit(self, pipeline_id=None, previous_id=None, output_root=None, collection_target=None):
        previous = self.c.task_registry.get(previous_id) if previous_id else None
        if previous_id:
            if not previous:
                raise LibraryError('任务不存在', 404)
            if previous['status'] == 'completed':
                artifacts = previous.get('output', {}).get('artifacts', [])
                training = [a for a in artifacts if a['kind'] == 'training']
                if not training or any(not Path(a['path']).is_file() or _hash(Path(a['path']).read_bytes()) != a['sha256'] for a in artifacts):
                    raise LibraryError('完成任务产物不完整或已变化，不能复用', 409)
                return {'task_id': previous_id, 'status': 'completed', 'reused': True}
            if previous['status'] not in {'failed', 'cancelled'}:
                raise LibraryError('任务仍在排队或运行，不能重跑', 409)
            config = copy.deepcopy(previous['pipeline_config'])
            pipeline_id = previous.get('pipeline_id')
        else:
            pipeline = self.c.pipeline_registry.get_pipeline(pipeline_id)
            if not pipeline:
                raise LibraryError('配置不存在', 404)
            config = copy.deepcopy(pipeline['config'])
        if config.get('execution_options', {}).get('representative_training'):
            from app.services.representative_training import isolate_rows
            config = isolate_rows(config)
        from app.services.personal_execution import bind
        bind(config)
        check = self.preflight(config)
        if not check['ready']:
            raise LibraryError('；'.join(check['errors']), 422)
        options = config.setdefault('execution_options', {})
        from app.services.auto_collection import freeze_collection_target
        if collection_target is not None:
            options['collection_target'] = collection_target
        freeze_collection_target(config, self.c.data_library)
        from app.services.source_progress import content_identity, dataset_id
        source_id=dataset_id(config)
        source_record=self.c.dataset_registry.get(source_id)
        before=content_identity(dict(source_record,id=source_id)) if source_record and not options.get('input_snapshot') else None
        options['input_snapshot'] = self._freeze_input(config)
        if before is not None:
            after=content_identity(dict(source_record,id=source_id))
            if before!=after:raise LibraryError('固定输入期间原始内容变化，请重试',409)
            options['source_identity']=before
        options.update(capture_responses=True, training_output=True, max_attempts=options.get('additional_retries', 0)+1,
                       serving_snapshots=check['serving_snapshots'])
        # Resolve resources and all runtime conditions BEFORE writing queued.
        config, resources = resolve_pipeline_resources(config)
        from app.services.dataflow_engine import DataFlowEngine
        from app.services.ray_pipeline_executor import ray_executor
        task_id = self.c.task_registry._generate_task_id()
        from app.services.result_storage import prepare
        if output_root is not None:
            config.setdefault('execution_options', {})['output_root'] = output_root
        if config.get('execution_options', {}).get('output_root'):
            prepare(config, task_id, previous.get('name', '文本生成') if previous else pipeline.get('name', '文本生成'))
        for op in config['operators']:
            if op['name'] == 'MinerU4PDFParser':
                for param in op['params']['init']:
                    if param['name'] == 'output_dir':
                        param['value'] = str(Path(settings.CACHE_DIR) / f'{task_id}_output' / 'parsing')
        runtime = DataFlowEngine.decode_hashed_arguments(config, task_id)
        for sid, snapshot in check['serving_snapshots'].items():
            info = runtime.get('serving_map', {}).get(sid)
            if info is not None:
                parameters = {k: v for k, v in serving_parameters(info).items() if k not in {'api_key', 'key_name_of_api_key'}}
                if parameters != snapshot['parameters']:
                    raise LibraryError('提交期间服务配置发生变化，请重新检查', 409)
        # Native Ray runtime keeps actual credentials only in memory.
        record = {'task_id': task_id, 'pipeline_id': pipeline_id, 'name': previous.get('name', '文本生成重跑') if previous else pipeline.get('name', '文本生成'), 'pipeline_config': config,
                  'pipeline_source_config': previous.get('pipeline_source_config') if previous else pipeline['config'],
                  'resource_snapshots': previous.get('resource_snapshots', []) if previous else resources,
                  'status': 'queued', 'created_at': _now(), 'output': {}, 'logs': ['整批任务排队；额外重试 '+str(options.get('additional_retries', 0))],
                  'retry_of': previous_id, 'progress_unit': 'batch'}
        patch_task(self.c.task_registry.path, task_id, record, create=True)
        try:
            await ray_executor.submit_execution(config, runtime, task_id, self.c.pipeline_registry.path, self.c.task_registry.path)
        except Exception as exc:
            from app.services.task_store import fail_submission
            fail_submission(self.c.task_registry.path, task_id, exc)
            raise LibraryError('任务提交失败，已记录失败原因', 503) from exc
        return {'task_id': task_id, 'status': 'queued', 'reused': False}

    def detail(self, task_id):
        task = self.c.task_registry.get(task_id)
        if not task:
            raise LibraryError('任务不存在', 404)
        task = copy.deepcopy(task)
        steps = task.get('output', {}).get('operators_detail', {})
        task['progress'] = {'unit': 'batch', 'completed': int(task['status']=='completed'), 'total': 1,
                            'steps_completed': sum(s.get('status')=='completed' for s in steps.values()),
                            'steps_total': len(task.get('pipeline_config', {}).get('operators', []))}
        return task
