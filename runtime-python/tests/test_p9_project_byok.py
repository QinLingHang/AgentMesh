from types import SimpleNamespace

from pydantic import SecretStr

from app.models.runtime import ModelRuntimeResolver
from app.schemas import AgentProfile, ProjectModelRuntime


def test_project_byok_contract_masks_secret_in_repr_and_json():
    model = ProjectModelRuntime(
        provider="openai-compatible",
        baseUrl="https://api.example.test/v1",
        modelName="project-model",
        apiKey="sk-secret-value",
    )
    assert isinstance(model.api_key, SecretStr)
    assert "sk-secret-value" not in repr(model)
    assert "sk-secret-value" not in model.model_dump_json(by_alias=True)
    assert model.api_key.get_secret_value() == "sk-secret-value"


def test_project_byok_resolver_is_request_local(monkeypatch):
    captured = {}

    class FakeProvider:
        name = "openai_compatible"
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class FakeContext:
        def __init__(self):
            self.lookups = []
        def get(self, key):
            self.lookups.append(key)
            return SimpleNamespace(model="global-model", provider="mock", gateway=object())

    import app.models.runtime as runtime_module
    monkeypatch.setattr(runtime_module, "OpenAICompatibleModelProvider", FakeProvider)

    context = FakeContext()
    resolver = ModelRuntimeResolver.__new__(ModelRuntimeResolver)
    resolver._context = context
    resolver.model_router = SimpleNamespace()

    agent = AgentProfile(id=1, name="General", endpoint="internal://general", protocol="internal", capabilities=["general"])
    project_model = ProjectModelRuntime(provider="openai-compatible", baseUrl="https://api.example.test/v1", modelName="tenant-model", apiKey="tenant-key")
    resolved = resolver.resolve(agent, project_model=project_model)

    assert resolved.runtime_id == "project-byok"
    assert resolved.model == "tenant-model"
    assert captured["api_key"] == "tenant-key"
    assert captured["trust_env"] is False
    assert context.lookups == []  # no mutation/lookup of the global runtime pool
