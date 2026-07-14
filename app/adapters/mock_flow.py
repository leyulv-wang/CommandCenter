from app.forms.schemas import EndpointType


class MockExternalSubmitter:
    def submit(
        self, endpoint_type: EndpointType, url: str, payload: dict[str, object]
    ) -> dict[str, object]:
        stable_seed = f"{endpoint_type}:{url}:{len(str(payload))}"
        ticket_id = "MOCK-" + str(abs(hash(stable_seed)))[:10]
        return {
            "ok": True,
            "ticket_id": ticket_id,
            "endpoint_type": endpoint_type,
            "submit_mode": "mock",
            "payload": payload,
        }
