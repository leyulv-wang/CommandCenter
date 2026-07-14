from __future__ import annotations

import json
from pathlib import Path

from app.forms.schemas import FormTemplate


class FormTemplateRepository:
    def __init__(self, templates_dir: Path | None = None) -> None:
        self.templates_dir = templates_dir or (
            Path(__file__).resolve().parents[1] / "data" / "form_templates"
        )

    def get(self, form_code: str) -> FormTemplate:
        path = self.templates_dir / f"{form_code}.json"
        if not path.exists():
            raise KeyError(f"Unknown form template: {form_code}")
        return FormTemplate.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[FormTemplate]:
        return [self.get(path.stem) for path in sorted(self.templates_dir.glob("*.json"))]

    def list_codes(self) -> list[str]:
        return [template.form_code for template in self.list()]

    def save(self, template: FormTemplate, overwrite: bool = False) -> None:
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        path = self.templates_dir / f"{template.form_code}.json"
        if path.exists() and not overwrite:
            raise FileExistsError(f"Form template already exists: {template.form_code}")
        path.write_text(
            json.dumps(template.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def delete_by_endpoint_base_url(
        self,
        base_url: str,
        exclude_codes: set[str] | None = None,
    ) -> list[str]:
        exclude_codes = exclude_codes or set()
        deleted_codes: list[str] = []
        for template in self.list():
            if (
                template.form_code not in exclude_codes
                and str(template.endpoint.url).startswith(base_url)
            ):
                path = self.templates_dir / f"{template.form_code}.json"
                path.unlink(missing_ok=True)
                deleted_codes.append(template.form_code)
        return deleted_codes
