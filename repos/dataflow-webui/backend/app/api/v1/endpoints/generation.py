"""Local text task wizard and task-to-dataset lifecycle."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from app.api.v1.resp import ok
from app.core.container import container
from app.services.data_library import LibraryError, _hash
from app.services.text_generation import TextGeneration, template
from app.services.training_lifecycle import TrainingLifecycle
from pathlib import Path

router = APIRouter(tags=['generation'])


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


class SaveConfig(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    config: dict
    pipeline_id: str | None = None


class SampleEdit(BaseModel):
    row: dict
    expected_updated_at: str | None = None


class FieldMap(BaseModel):
    mapping: dict[str, str]


class Collect(BaseModel):
    draft_id: str
    artifact_id: str


@router.get('/template')
def get_template():
    return ok(template())


@router.post('/configs')
def save_config(body: SaveConfig):
    return ok(call(TextGeneration().save, body.name, body.config, body.pipeline_id))


@router.get('/configs/{pipeline_id}/check')
def check_config(pipeline_id: str):
    pipeline = container.pipeline_registry.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(404, '配置不存在')
    return ok(TextGeneration().preflight(pipeline['config']))


@router.post('/configs/{pipeline_id}/submit')
async def submit(pipeline_id: str):
    try:
        return ok(await TextGeneration().submit(pipeline_id=pipeline_id))
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get('/tasks')
def tasks():
    records = container.task_registry.list_executions()
    # Keep historical tasks reachable in the existing canvas; list platform tasks here.
    return ok([{k: v for k, v in rec.items() if k in {'task_id', 'pipeline_id', 'name', 'status', 'created_at', 'started_at', 'completed_at', 'retry_of'}}
               for rec in records if rec.get('pipeline_config', {}).get('execution_options', {}).get('capture_responses')])


@router.get('/tasks/{task_id}')
def detail(task_id: str):
    return ok(call(TextGeneration().detail, task_id))


@router.post('/tasks/{task_id}/retry')
async def retry(task_id: str):
    try:
        return ok(await TextGeneration().submit(previous_id=task_id))
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def artifact(task_id, artifact_id):
    task = call(TextGeneration().detail, task_id)
    item = next((a for a in task.get('output', {}).get('artifacts', []) if a['id'] == artifact_id), None)
    if not item:
        raise HTTPException(404, '任务产物不存在')
    return task, item


@router.get('/tasks/{task_id}/artifacts/{artifact_id}')
def download_artifact(task_id: str, artifact_id: str):
    _, item = artifact(task_id, artifact_id)
    path = Path(item['path'])
    if not path.is_file() or _hash(path.read_bytes()) != item['sha256']:
        raise HTTPException(409, '任务产物缺失或已变化')
    return FileResponse(path, filename=f'{task_id}_{artifact_id}.jsonl', media_type='application/x-ndjson')


@router.post('/tasks/{task_id}/collect')
def collect(task_id: str, body: Collect):
    task, item = artifact(task_id, body.artifact_id)
    return ok(call(TrainingLifecycle(container.data_library).collect, body.draft_id, task, item))


@router.put('/drafts/{draft_id}/samples/{sample_id}')
def edit_sample(draft_id: str, sample_id: str, body: SampleEdit):
    return ok(call(TrainingLifecycle(container.data_library).edit, draft_id, sample_id, body.row, expected_updated_at=body.expected_updated_at))


@router.delete('/drafts/{draft_id}/samples/{sample_id}')
def delete_sample(draft_id: str, sample_id: str):
    return ok(call(TrainingLifecycle(container.data_library).edit, draft_id, sample_id, delete=True))


@router.post('/drafts/{draft_id}/map-fields')
def map_fields(draft_id: str, body: FieldMap):
    return ok(call(TrainingLifecycle(container.data_library).map_fields, draft_id, body.mapping))


@router.get('/drafts/{draft_id}/releases')
def list_releases(draft_id: str):
    return ok(call(TrainingLifecycle(container.data_library).list_releases, draft_id))


@router.post('/drafts/{draft_id}/publish')
def publish(draft_id: str):
    return ok(call(TrainingLifecycle(container.data_library).publish, draft_id))


@router.get('/releases/{release_id}/download')
def download_release(release_id: str, format: str = 'package'):
    path = call(TrainingLifecycle(container.data_library).download, release_id, format)
    return FileResponse(path, filename=path.name, media_type='application/zip' if format=='package' else 'application/x-ndjson')


@router.post('/releases/{release_id}/fork')
def fork_release(release_id: str):
    return ok(call(TrainingLifecycle(container.data_library).fork, release_id))
