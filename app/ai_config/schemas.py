from pydantic import BaseModel, Field

from app.forms.schemas import FormTemplate


class GenerateFormConfigRequest(BaseModel):
    form_name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class GenerateFormConfigResponse(BaseModel):
    draft_config: FormTemplate
    warnings: list[str] = Field(default_factory=list)
