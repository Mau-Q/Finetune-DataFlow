from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from app.schemas.pipelines import Pipeline

class DatasetIn(BaseModel):
    name: str
    root: str
    pipeline: str = Field(
        ...,
        description="指定一个或多个该数据集适合的 pipeline"
    )
    meta: Dict[str, str] = Field(default_factory=dict)

class DatasetOut(DatasetIn):
    is_visible: bool = True
    type: str = ""
    content_type: Optional[str] = None
    file_count: Optional[int] = None
    added_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    id: str
    num_samples: int = 0
    file_size: int = 0
    hash: Optional[str] = None
