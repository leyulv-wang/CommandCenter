import json
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import form_execution_graph
from app.command_center.agents import AgentSuite
from app.command_center.execution_graph import (
    ExecutionDependencies,
    LocalBusinessReader,
    build_execution_graph,
)
from app.command_center.learning_graph import LearningDependencies, build_learning_graph
from app.command_center.model import StructuredModel
from app.command_center.recorder import RecorderService
from app.command_center.repository import CommandCenterRepository
from app.command_center.router import create_router
from app.command_center.service import CommandCenterService
from app.command_center.testing import (
    HarmlessTestService,
    LocalFixtureService,
    SkillRunner,
)
from app.command_center.tool_catalog import ToolCatalog
from app.command_center.tool_executor import ToolExecutor
from app.ai_config.generator import generate_form_config
from app.ai_config.schemas import (
    GenerateFormConfigRequest,
    GenerateFormConfigResponse,
)
from app.external_systems import ExternalSystemClient
from app.forms.repository import FormTemplateRepository
from app.forms.schemas import FormSubmission, FormTemplate


app = FastAPI(title="Configurable Form Agent MVP")
external_system_client = ExternalSystemClient()
_command_center_service: CommandCenterService | None = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:8101",
        "http://localhost:8101",
        "http://127.0.0.1:8102",
        "http://localhost:8102",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_command_center_service() -> CommandCenterService:
    global _command_center_service
    if _command_center_service is None:
        _command_center_service = _build_command_center_service()
    return _command_center_service


app.include_router(create_router(get_command_center_service))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/forms", response_model=list[FormTemplate])
def list_forms() -> list[FormTemplate]:
    return FormTemplateRepository().list()


@app.post("/forms", response_model=FormTemplate, status_code=201)
def create_form(template: FormTemplate) -> FormTemplate:
    try:
        FormTemplateRepository().save(template, overwrite=False)
        external_system_client.registry.connect_form_by_endpoint(
            str(template.endpoint.url),
            template.form_code,
        )
        return template
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/forms/{form_code}", response_model=FormTemplate)
def get_form(form_code: str) -> FormTemplate:
    try:
        return FormTemplateRepository().get(form_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/forms/{form_code}/submit")
def submit_form(form_code: str, submission: FormSubmission) -> dict[str, object]:
    try:
        state = form_execution_graph.invoke(
            {
                "form_code": form_code,
                "operator_id": submission.operator_id,
                "values": submission.values,
            }
        )
        return state["result"]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/external-systems")
def list_external_systems() -> list[dict[str, object]]:
    return external_system_client.list_systems()


@app.get("/tasks")
def list_tasks(
    operator_id: str = "u001",
    status: Literal["pending", "completed"] = "pending",
) -> dict[str, object]:
    try:
        return {
            "operator_id": operator_id,
            "items": external_system_client.list_tasks(operator_id, status),
        }
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"外部任务读取失败：{exc}") from exc


@app.post("/tasks/{system_code}/{task_id}/complete")
def complete_task(
    system_code: str,
    task_id: str,
    submission: FormSubmission,
) -> dict[str, object]:
    try:
        task = external_system_client.get_task(
            system_code,
            task_id,
            submission.operator_id,
        )
        state = form_execution_graph.invoke(
            {
                "form_code": task["form_code"],
                "operator_id": submission.operator_id,
                "values": submission.values,
                "context_values": {"task_id": task_id},
            }
        )
        result = state["result"]
        if not result.get("ok", False):
            raise HTTPException(
                status_code=502,
                detail=f"外部任务处理失败：{result.get('error', '未知错误')}",
            )
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"任务处理提交失败：{exc}") from exc


@app.get("/external-systems/{system_code}/submissions")
def list_external_submissions(system_code: str) -> dict[str, object]:
    try:
        return external_system_client.list_submissions(system_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"外部系统读取失败：{exc}") from exc


@app.get("/external-systems/{system_code}/data")
def get_external_system_data(system_code: str) -> dict[str, object]:
    try:
        return external_system_client.get_system_data(system_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"外部系统数据读取失败：{exc}") from exc


@app.get("/external-systems/{system_code}/forms", response_model=list[FormTemplate])
def list_external_system_forms(system_code: str) -> list[FormTemplate]:
    try:
        repository = FormTemplateRepository()
        return [
            repository.get(form_code)
            for form_code in external_system_client.list_form_codes(system_code)
        ]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/external-systems/{system_code}/interface-spec")
def get_external_interface_spec(system_code: str) -> dict[str, object]:
    try:
        return external_system_client.get_interface_spec(system_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"外部系统读取失败：{exc}") from exc


@app.post("/demo/reset-onboarding")
def reset_onboarding_demo() -> dict[str, object]:
    return _reset_demo_system("onboarding_system")


@app.post("/demo/reset/{system_code}")
def reset_demo_system(system_code: str) -> dict[str, object]:
    return _reset_demo_system(system_code)


def _reset_demo_system(system_code: str) -> dict[str, object]:
    try:
        system = external_system_client.registry.get(system_code)
        protected_form_codes = {
            "connected_system": {"purchase_task_result"},
            "onboarding_system": {"office_supply_task_result"},
        }
        if system_code not in protected_form_codes:
            raise KeyError(f"Demo system not found: {system_code}")
        external_result = external_system_client.reset_demo_system(system_code)
        deleted_form_codes = FormTemplateRepository().delete_by_endpoint_base_url(
            system["base_url"],
            exclude_codes=protected_form_codes[system_code],
        )
        external_system_client.registry.reset_onboarding(system_code)
        return {
            "ok": True,
            "deleted_form_codes": deleted_form_codes,
            "external_result": external_result,
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"外部系统重置失败：{exc}") from exc


def _build_command_center_service() -> CommandCenterService:
    base_urls = {
        "connected_system": "http://127.0.0.1:8101",
        "onboarding_system": "http://127.0.0.1:8102",
    }
    client = httpx.Client(timeout=30)
    documents = {
        system_code: client.get(f"{base_url}/openapi.json").raise_for_status().json()
        for system_code, base_url in base_urls.items()
    }
    allowlist = {
        ("connected_system", "start_workflow_api_workflows_start_post"),
        ("connected_system", "list_submissions_api_submissions_get"),
        ("onboarding_system", "list_tasks_api_tasks_get"),
        ("onboarding_system", "get_task_api_tasks__task_id__get"),
        (
            "onboarding_system",
            "link_purchase_request_api_tasks__task_id__purchase_link_post",
        ),
    }
    catalog = ToolCatalog.from_openapi_documents(
        documents,
        base_urls,
        allowlist,
    )
    repository = CommandCenterRepository(
        "sqlite:///app/data/command_center.sqlite3"
    )
    agents = AgentSuite(StructuredModel.from_environment())
    runner = SkillRunner(ToolExecutor(catalog, client))
    fixture = LocalFixtureService(client=client, base_urls=base_urls)
    harmless_tests = HarmlessTestService(
        fixture_service=fixture,
        runner=runner,
        verifier=agents,
    )
    learning_graph = build_learning_graph(
        LearningDependencies(
            repository=repository,
            agents=agents,
            tester=harmless_tests,
            catalog=catalog,
        )
    )
    business_reader = LocalBusinessReader(client, base_urls)
    execution_graph = build_execution_graph(
        ExecutionDependencies(
            skills=repository.list_published_skills,
            business_reader=business_reader,
            agents=agents,
            runner=runner,
        )
    )
    recorder = RecorderService(
        catalog,
        Path("app/data/command_center_evidence"),
    )
    return CommandCenterService(
        repository=repository,
        recorder=recorder,
        learning_graph=learning_graph,
        execution_graph=execution_graph,
    )


@app.post("/ai/form-config/generate", response_model=GenerateFormConfigResponse)
def generate_ai_form_config(
    request: GenerateFormConfigRequest,
) -> GenerateFormConfigResponse | dict[str, object]:
    try:
        return generate_form_config(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"模型返回的 JSON 无法解析：{exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型服务调用失败：{exc}") from exc
