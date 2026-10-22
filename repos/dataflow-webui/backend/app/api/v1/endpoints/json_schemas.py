from app.services.resource_store import ResourceConflictError
from fastapi import APIRouter, HTTPException, status
from loguru import logger as log
from app.schemas.json_schema import JsonSchemaCreate, JsonSchemaUpdate, JsonSchemaOut
from app.core.container import container
from app.api.v1.resp import ok
from app.api.v1.envelope import ApiResponse
from typing import List


router = APIRouter(tags=["json_schemas"])


@router.post('/validate', response_model=ApiResponse[dict], summary='按标准校验 Schema 与示例（不保存）')
def validate_schema_preview(body: JsonSchemaCreate):
    from app.services.json_schema_manager import validate_schema
    try:
        validate_schema(body.schema, body.example or '')
        return ok({'valid': True})
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def _manager():
    return container.json_schema_manager


@router.post("/", response_model=ApiResponse[JsonSchemaOut], include_in_schema=False)
@router.post(
    "",
    response_model=ApiResponse[JsonSchemaOut],
    summary="创建新的 JSON Schema"
)
def create_schema(schema_in: JsonSchemaCreate):
    """Create a new JSON schema."""
    try:
        schema_out = _manager().create(
            name=schema_in.name,
            description=schema_in.description or "",
            schema=schema_in.schema,
            example=schema_in.example or "",
            usage=schema_in.usage, purpose=schema_in.purpose
        )
        return ok(JsonSchemaOut(**schema_out))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.error(f"Failed to create schema: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/catalog')
def schema_catalog():
    from app.services.resource_catalog import ResourceCatalog
    return ok(ResourceCatalog().schemas())


@router.get("/", response_model=ApiResponse[List[JsonSchemaOut]], include_in_schema=False)
@router.get(
    "",
    response_model=ApiResponse[List[JsonSchemaOut]],
    summary="获取所有 JSON Schemas"
)
def list_schemas(include_builtin: bool = False):
    """List all JSON schemas."""
    try:
        schemas = _manager().list_all()
        if include_builtin:
            from app.services.builtin_resources import builtin_schemas
            schemas += builtin_schemas()
        return ok([JsonSchemaOut(**s) for s in schemas])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.error(f"Failed to list schemas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{schema_id}",
    response_model=ApiResponse[JsonSchemaOut],
    summary="根据 ID 获取 JSON Schema"
)
def get_schema(schema_id: str):
    """Get a schema by ID."""
    try:
        schema = _manager().get(schema_id)
        if not schema:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema {schema_id} not found"
            )
        return ok(JsonSchemaOut(**schema))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.error(f"Failed to get schema {schema_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put(
    "/{schema_id}",
    response_model=ApiResponse[JsonSchemaOut],
    summary="更新 JSON Schema"
)
def update_schema(schema_id: str, schema_update: JsonSchemaUpdate):
    """Update a schema by ID."""
    try:
        update_data = schema_update.dict(exclude_unset=True)
        schema = _manager().update(schema_id, **update_data)
        if not schema:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema {schema_id} not found"
            )
        return ok(JsonSchemaOut(**schema))
    except HTTPException:
        raise
    except ResourceConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.error(f"Failed to update schema {schema_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/{schema_id}",
    response_model=ApiResponse[dict],
    summary="删除 JSON Schema"
)
def delete_schema(schema_id: str):
    """Delete a schema by ID."""
    try:
        success = _manager().delete(schema_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Schema {schema_id} not found"
            )
        return ok({"deleted": True, "id": schema_id})
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.error(f"Failed to delete schema {schema_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
