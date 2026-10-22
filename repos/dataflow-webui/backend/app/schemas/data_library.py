"""Contracts for source materials and training drafts, separate from legacy inputs."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class MaterialMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=240)
    group: str = Field(default='', max_length=120)
    source: str = Field(default='', max_length=2000)
    description: str = Field(default='', max_length=4000)
    parent_material_id: str | None = None
    relation: Literal['source', 'parsed_image', 'parsed_table', 'parsed_formula', 'page_image'] = 'source'


class MaterialRegister(MaterialMetadata):
    path: str


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=240)
    modality: Literal['text', 'image_text'] = 'text'
    training_type: Literal['sft', 'dpo'] = 'sft'
    description: str = Field(default='', max_length=4000)
