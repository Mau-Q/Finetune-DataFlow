from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, Literal
from datetime import datetime


class JsonSchemaCreate(BaseModel):
    """创建 JSON Schema 时的输入"""
    usage: Literal['通用', '文本 SFT', '图文 SFT', '文本 DPO', '图文 DPO'] = '通用'
    purpose: Literal['通用', '模型输出', '训练样本校验'] = '通用'
    name: str = Field(..., description="Schema 的名称")
    description: Optional[str] = Field("", description="Schema 的描述")
    schema: str = Field(..., description="JSON Schema 定义（JSON 字符串）")
    example: Optional[str] = Field("", description="示例数据（JSON 字符串）")


class JsonSchemaUpdate(BaseModel):
    expected_updated_at: Optional[str] = None
    """更新 JSON Schema 时的输入"""
    usage: Optional[Literal['通用', '文本 SFT', '图文 SFT', '文本 DPO', '图文 DPO']] = None
    purpose: Optional[Literal['通用', '模型输出', '训练样本校验']] = None
    name: Optional[str] = Field(None, description="Schema 的名称")
    description: Optional[str] = Field(None, description="Schema 的描述")
    schema: Optional[str] = Field(None, description="JSON Schema 定义（JSON 字符串）")
    example: Optional[str] = Field(None, description="示例数据（JSON 字符串）")


class JsonSchemaOut(BaseModel):
    """JSON Schema 的输出"""
    id: str = Field(..., description="Schema 的唯一标识符")
    usage: Literal['通用', '文本 SFT', '图文 SFT', '文本 DPO', '图文 DPO'] = '通用'
    purpose: Literal['通用', '模型输出', '训练样本校验'] = '通用'
    name: str = Field(..., description="Schema 的名称")
    description: str = Field("", description="Schema 的描述")
    schema: str = Field(..., description="JSON Schema 定义（JSON 字符串）")
    example: str = Field("", description="示例数据（JSON 字符串）")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")
