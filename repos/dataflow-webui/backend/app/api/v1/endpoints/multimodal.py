"""MM configuration endpoints. Submission is deliberately non-dispatching."""
from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.api.v1.resp import ok
from app.api.v1.endpoints.generation import call
from app.services.multimodal_templates import MultimodalTemplates, template

router = APIRouter(tags=['multimodal'])


class SaveConfig(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    config: dict
    config_id: str | None = None


@router.get('/template')
def get_template():
    return ok(template())


@router.get('/configs')
def list_configs():
    return ok(MultimodalTemplates().store.list_all())


@router.post('/configs')
def save(body: SaveConfig):
    return ok(call(MultimodalTemplates().save, body.name, body.config, body.config_id))


@router.get('/configs/{config_id}')
def get(config_id: str):
    return ok(call(MultimodalTemplates().get, config_id))


@router.get('/configs/{config_id}/check')
def check(config_id: str):
    service = MultimodalTemplates()
    return ok(service.check(call(service.get, config_id)['config']))


@router.post('/configs/{config_id}/submit')
def submit(config_id: str):
    return ok(call(MultimodalTemplates().submit, config_id))
