from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


# Ответ на загрузку сценария
class SceneUploadResponse(BaseModel):
    doc_id: str
    scenes: List[Dict[str, Any]]


# Пересчёт одной сцены
class SceneRecalcRequest(BaseModel):
    scene: Dict[str, Any]
    edited_text: Optional[str] = None
    checksum: Optional[str] = None


# Замена AI-фрагмента
class ReplaceFragmentRequest(BaseModel):
    scene: Dict[str, Any]
    fragment_original: str
    fragment_new: str


# Отмена нарушения
class CancelViolationRequest(BaseModel):
    scene_index: int
    fragment_text: str


# Экспорт
class ExportRequest(BaseModel):
    format: str = Field(pattern="^(pdf|html|docx|html)$")


class ExportResponse(BaseModel):
    url: str
    format: str


# Статус
class StatusResponse(BaseModel):
    doc_id: str
    status: str
    dirty_global: bool
    dirty_scenes: List[int]