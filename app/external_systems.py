from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TypedDict

import httpx


ExternalSystemRole = Literal["connected", "onboarding"]


class ExternalSystem(TypedDict):
    system_code: str
    system_name: str
    base_url: str
    role: ExternalSystemRole
    form_codes: list[str]


class ExternalSystemRegistry:
    def __init__(
        self,
        systems: list[ExternalSystem] | None = None,
        state_path: Path | None = None,
    ) -> None:
        self._state_path = state_path
        if systems is not None:
            self._systems = systems
            return

        if self._state_path is None:
            self._state_path = Path(__file__).parent / "data" / "external_systems.json"
        if self._state_path.exists():
            self._systems = json.loads(self._state_path.read_text(encoding="utf-8"))
        else:
            self._systems = self._default_systems()
            self._save()

    @staticmethod
    def _default_systems() -> list[ExternalSystem]:
        return [
            {
                "system_code": "connected_system",
                "system_name": "采购业务系统",
                "base_url": "http://127.0.0.1:8101",
                "role": "onboarding",
                "form_codes": [],
            },
            {
                "system_code": "onboarding_system",
                "system_name": "办公用品系统",
                "base_url": "http://127.0.0.1:8102",
                "role": "onboarding",
                "form_codes": [],
            },
        ]

    def list(self) -> list[ExternalSystem]:
        return self._systems

    def get(self, system_code: str) -> ExternalSystem:
        for system in self._systems:
            if system["system_code"] == system_code:
                return system
        raise KeyError(f"External system not found: {system_code}")

    def connect_form_by_endpoint(
        self,
        endpoint_url: str,
        form_code: str,
    ) -> ExternalSystem | None:
        normalized_url = endpoint_url.rstrip("/")
        for system in self._systems:
            base_url = system["base_url"].rstrip("/")
            if normalized_url != base_url and not normalized_url.startswith(f"{base_url}/"):
                continue
            system["role"] = "connected"
            if form_code not in system["form_codes"]:
                system["form_codes"].append(form_code)
            self._save()
            return system
        return None

    def reset_onboarding(self, system_code: str) -> ExternalSystem:
        system = self.get(system_code)
        system["role"] = "onboarding"
        system["form_codes"] = []
        self._save()
        return system

    def _save(self) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(self._systems, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class ExternalSystemClient:
    def __init__(
        self,
        registry: ExternalSystemRegistry | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.registry = registry or ExternalSystemRegistry()
        self.http_client = http_client or httpx.Client(timeout=5)

    def list_systems(self) -> list[ExternalSystem]:
        return self.registry.list()

    def list_submissions(self, system_code: str) -> dict[str, object]:
        system = self.registry.get(system_code)
        response = self.http_client.get(f"{system['base_url']}/api/submissions")
        response.raise_for_status()
        return response.json()

    def get_system_data(self, system_code: str) -> dict[str, object]:
        system = self.registry.get(system_code)
        if system["role"] != "connected":
            raise KeyError(f"External system is not connected: {system_code}")

        tasks: list[dict[str, Any]] = []
        for status in ("pending", "completed"):
            response = self.http_client.get(
                f"{system['base_url']}/api/tasks",
                params={"status": status},
            )
            response.raise_for_status()
            tasks.extend(
                {
                    **item,
                    "source_system_code": system["system_code"],
                    "source_system_name": system["system_name"],
                }
                for item in response.json().get("items", [])
            )

        response = self.http_client.get(f"{system['base_url']}/api/submissions")
        response.raise_for_status()
        submissions = response.json().get("items", [])
        return {
            "system": {
                "system_code": system["system_code"],
                "system_name": system["system_name"],
            },
            "tasks": tasks,
            "submissions": submissions,
        }

    def get_interface_spec(self, system_code: str) -> dict[str, object]:
        system = self.registry.get(system_code)
        response = self.http_client.get(f"{system['base_url']}/api/interface-spec")
        response.raise_for_status()
        return response.json()

    def list_tasks(
        self,
        operator_id: str,
        status: Literal["pending", "completed"] = "pending",
    ) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for system in self.registry.list():
            if system["role"] != "connected":
                continue
            params = {"operator_id": operator_id}
            if status != "pending":
                params["status"] = status
            response = self.http_client.get(f"{system['base_url']}/api/tasks", params=params)
            response.raise_for_status()
            for item in response.json().get("items", []):
                tasks.append(
                    {
                        **item,
                        "source_system_code": system["system_code"],
                        "source_system_name": system["system_name"],
                    }
                )
        tasks.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return tasks

    def list_form_codes(self, system_code: str) -> list[str]:
        system = self.registry.get(system_code)
        if system["role"] != "connected":
            raise KeyError(f"External system is not connected: {system_code}")
        return system.get("form_codes", [])

    def get_task(
        self,
        system_code: str,
        task_id: str,
        operator_id: str,
    ) -> dict[str, Any]:
        system = self.registry.get(system_code)
        if system["role"] != "connected":
            raise KeyError(f"External system is not connected: {system_code}")
        response = self.http_client.get(
            f"{system['base_url']}/api/tasks",
            params={"operator_id": operator_id},
        )
        response.raise_for_status()
        for item in response.json().get("items", []):
            if item.get("task_id") == task_id:
                return item
        raise KeyError(f"Task not found: {task_id}")

    def reset_demo_system(self, system_code: str) -> dict[str, object]:
        system = self.registry.get(system_code)
        response = self.http_client.post(f"{system['base_url']}/api/demo/reset")
        response.raise_for_status()
        return response.json()
