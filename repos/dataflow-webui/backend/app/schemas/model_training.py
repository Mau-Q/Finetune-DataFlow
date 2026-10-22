"""Versioned training definitions; these never import DataFlex into WebUI."""
from typing import Literal, Any
from pydantic import BaseModel, Field, ConfigDict

class DataBinding(BaseModel):
    model_config = ConfigDict(extra='allow')
    role: Literal['train', 'validation', 'reference'] = 'train'
    kind: Literal['release', 'file', 'huggingface', 'draft'] = 'release'
    ref: str = ''
    domain: str = 'default'
    revision: str = ''
    subset: str = ''
    split: str = 'train'
    sha256: str = ''
    columns: dict[str, str] = Field(default_factory=lambda: {'prompt':'instruction','query':'input','response':'output'})

class TrainingPlan(BaseModel):
    model_config = ConfigDict(extra='allow')
    name: str = Field(default='新训练方案', min_length=1, max_length=240)
    model: str = ''
    tokenizer: str = ''
    model_revision: str = ''
    template: str = 'qwen'
    task: Literal['sft', 'pt', 'dpo'] = 'sft'
    modality: Literal['text', 'image_text'] = 'text'
    finetuning_type: Literal['lora', 'full'] = 'lora'
    max_steps: int = Field(default=100, ge=1)
    batch_size: int = Field(default=1, ge=1)
    gradient_accumulation_steps: int = Field(default=8, ge=1)
    learning_rate: float = Field(default=0.0001, gt=0)
    seed: int = 42
    data: list[DataBinding] = Field(default_factory=list)
    group_id: str | None = None
    strategy: dict[str, Any] = Field(default_factory=lambda: {'family':'static','component':'','params':{}})
    advanced: dict[str, Any] = Field(default_factory=dict)

class PlanSave(BaseModel):
    plan: TrainingPlan
    expected_version: int | None = None

class ExperimentGroup(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    shared_conditions: dict = Field(default_factory=dict)
    allowed_differences: list[str] = Field(default_factory=list)
