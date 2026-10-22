"""Source materials, compatible input manifests and training drafts."""
import json
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError
from app.api.v1.resp import ok
from app.core.container import container
from app.schemas.data_library import DraftCreate, MaterialMetadata, MaterialRegister
from app.services.data_library import LibraryError, MAX_BYTES, MAX_IMPORT_BYTES
from app.services.dataset_visibility import visible_drafts

router = APIRouter(tags=['data_library'])


def _call(method, *args, **kwargs):
    try:
        return method(*args, **kwargs)
    except LibraryError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get('/materials')
def list_materials():
    return ok(container.data_library.list_materials())


@router.post('/materials/upload')
def upload_material(file: UploadFile = File(...), metadata: str = Form('{}')):
    try:
        fields = json.loads(metadata)
        meta = MaterialMetadata.model_validate(fields).model_dump()
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, f'材料元数据无效: {exc}') from exc
    content = file.file.read(MAX_BYTES + 1)
    return ok(_call(container.data_library.add_material, file.filename or '', content, meta))


@router.post('/materials/register')
def register_material(request: MaterialRegister):
    return ok(_call(container.data_library.register_material, request))


@router.get('/materials/{material_id}')
def get_material(material_id: str):
    return ok(_call(container.data_library.get_material, material_id))


@router.put('/materials/{material_id}')
def update_material(material_id: str, request: MaterialMetadata):
    return ok(_call(container.data_library.update_material, material_id, request.model_dump()))


@router.get('/materials/{material_id}/file')
def material_file(material_id: str):
    path, record = _call(container.data_library.material_file, material_id)
    return FileResponse(path, media_type=record['mime_type'], filename=record['filename'],
                        content_disposition_type='inline', headers={'X-Content-Type-Options': 'nosniff'})


@router.get('/drafts')
def list_drafts(visible_only: bool = False):
    records = container.data_library.list_drafts()
    return ok(visible_drafts(records) if visible_only else records)


@router.post('/drafts')
def create_draft(request: DraftCreate):
    return ok(_call(container.data_library.create_draft, request))


@router.get('/drafts/{draft_id}')
def get_draft(draft_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    return ok(_call(container.data_library.get_draft, draft_id, offset, limit))


@router.post('/drafts/{draft_id}/import')
def import_draft(draft_id: str, file: UploadFile = File(...), media_bindings: str = Form('{}')):
    try:
        bindings = json.loads(media_bindings)
    except ValueError as exc:
        raise HTTPException(400, '媒体映射必须是 JSON 对象') from exc
    return ok(_call(container.data_library.import_rows, draft_id, file.filename or '',
                    file.file.read(MAX_IMPORT_BYTES + 1), bindings))


@router.post('/inputs/upload')
def upload_source_dataset(files: list[UploadFile] = File(...), name: str = Form(...)):
    from app.services.source_datasets import SourceDatasets
    service = SourceDatasets(container.data_library, container.dataset_registry)
    return ok(_call(service.upload, files, name))


@router.post('/inputs/choose-local')
def choose_local_source():
    from app.services.local_source_picker import LocalSourcePicker
    return ok(_call(LocalSourcePicker(container.data_library, container.dataset_registry).choose))


@router.post('/inputs/import-local')
def import_local_source(selection_id: str = Form(...), name: str = Form(...)):
    from app.services.local_source_picker import LocalSourcePicker
    return ok(_call(LocalSourcePicker(container.data_library, container.dataset_registry).import_selection, selection_id, name))


@router.post('/inputs/upload-folder')
def upload_source_folder(files: list[UploadFile] = File(...), name: str = Form(...), from_directory: bool = Form(True)):
    from app.services.source_datasets import SourceDatasets
    service = SourceDatasets(container.data_library, container.dataset_registry)
    return ok(_call(service.upload_folder, files, name, 'folder' if from_directory else 'files'))


@router.get('/inputs/{dataset_id}/member-preview')
def source_member_preview(dataset_id: str, row: int = Query(0, ge=0), offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    from app.services.source_datasets import SourceDatasets
    service = SourceDatasets(container.data_library, container.dataset_registry)
    return ok(_call(service.member_preview, dataset_id, row, offset, limit))


@router.get('/inputs/{dataset_id}/file')
def source_dataset_file(dataset_id: str, row: int = Query(0, ge=0)):
    from app.services.source_datasets import SourceDatasets
    service = SourceDatasets(container.data_library, container.dataset_registry)
    path, mime = _call(service.file, dataset_id, row)
    return FileResponse(path, media_type=mime, filename=path.name,
                        content_disposition_type='inline', headers={'X-Content-Type-Options': 'nosniff'})


@router.get('/inputs/{dataset_id}/preview')
def source_dataset_preview(dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    from app.services.source_datasets import SourceDatasets
    service = SourceDatasets(container.data_library, container.dataset_registry)
    return ok(_call(service.preview, dataset_id, offset, limit))


@router.get('/storage/status')
def storage_status(request: Request):
    database = container.data_library.db
    with database.reading() as con:
        counts = {table: con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                  for table in ('source_datasets','source_members','materials','drafts','samples','draft_media','releases')}
    manager = getattr(request.app.state,'dataset_backups',None)
    archives = manager.archives() if manager else []
    return ok({'database':str(database.path),'schema_version':2,'counts':counts,
               'backup':{'enabled':bool(manager and manager._thread and manager._thread.is_alive()),
                         'interval_seconds':manager.interval if manager else None,
                         'latest':str(archives[0]) if archives else None,
                         'last_error':manager.last_error if manager else None,
                         'last_recovery':manager.last_recovery if manager else None}})
