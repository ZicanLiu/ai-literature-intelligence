"""Process-only credentials and explicit provider consent; never part of project storage."""
import os
from threading import RLock

from ..domain.models import WorkspaceError
from ..providers.openai_provider import OpenAIProvider
from ..providers.deepseek_provider import DeepSeekProvider

PROVIDERS = {"openai": OpenAIProvider, "deepseek": DeepSeekProvider}
DEEPSEEK_MODELS = ("deepseek-flash", "deepseek-v4-pro")


def hard_offline():
    return os.getenv("DISABLE_LIVE_API", "false").casefold() in {"true", "1"}


def model_capabilities(provider, model):
    known = provider == "deepseek" and model in DEEPSEEK_MODELS
    return {"text": True, "image": model == "deepseek-flash" if known else None,
            "json_schema": True if known else None,
            "reasoning_effort": known, "workspace_input_mode": "extracted_text"}


class LiveAISettings:
    def __init__(self):
        self._lock = RLock()
        self._keys = {name: None for name in PROVIDERS}
        self._models = {name: None for name in PROVIDERS}
        self._acknowledged = {name: False for name in PROVIDERS}
        self._auth_epochs = {name: 0 for name in PROVIDERS}
        self._offline_observed = hard_offline()
        self._effort = None
        self.selected_provider = "openai"
        self.live_enabled = False

    def _credential(self, provider):
        session = self._keys[provider]
        environment = os.getenv(f"{provider.upper()}_API_KEY")
        return (session, "session") if session else (environment, "environment" if environment else "none")

    def _model(self, provider):
        return self._models[provider] or os.getenv(f"COMPARISON_{provider.upper()}_MODEL")

    def status(self):
        with self._lock:
            offline = hard_offline()
            if offline and not self._offline_observed:
                for name in PROVIDERS:
                    self._auth_epochs[name] += 1
            self._offline_observed = offline
            providers = {}
            for name in PROVIDERS:
                key, source = self._credential(name)
                model = self._model(name)
                providers[name] = {"credential_configured": bool(key), "credential_source": source,
                                   "model": model, "consent_acknowledged": self._acknowledged[name],
                                   "reasoning_effort": self._effort if name == "deepseek" else None,
                                   "model_capabilities": model_capabilities(name, model),
                                   "suggested_models": list(DEEPSEEK_MODELS) if name == "deepseek" else []}
            selected = providers[self.selected_provider]
            enabled = bool(self.live_enabled and not offline and selected["credential_configured"]
                           and selected["model"] and selected["consent_acknowledged"])
            return {"selected_provider": self.selected_provider, "live_enabled": self.live_enabled,
                    "hard_offline": offline, "providers": providers, "api_enabled": enabled,
                    "api_model": selected["model"], "offline": not enabled}

    def update(self, provider, *, api_key=None, model=None, reasoning_effort=None,
               set_effort=False, live_enabled=None, acknowledge=None):
        with self._lock:
            if provider not in PROVIDERS:
                raise WorkspaceError("不支持的 AI 服务。")
            if model is not None and (model.startswith("sk-") or model == api_key):
                raise WorkspaceError("模型 ID 无效；请不要将 API Key 填入模型字段。")
            if provider == "deepseek" and model is not None and model not in DEEPSEEK_MODELS:
                raise WorkspaceError("请选择当前支持的 DeepSeek 模型。")
            if reasoning_effort not in {None, "none", "low", "high", "max"}:
                raise WorkspaceError("无效的 DeepSeek 思考强度。")
            if provider == "openai" and reasoning_effort is not None:
                raise WorkspaceError("OpenAI 不使用此 DeepSeek 思考设置。")
            # Omission preserves consent; explicit withdrawal wins over a simultaneous enable.
            if acknowledge is False:
                live_enabled = False
            consent = self._acknowledged[provider] if acknowledge is None else acknowledge
            if live_enabled and (hard_offline() or not (api_key or self._credential(provider)[0])
                                 or not (model or self._model(provider))
                                 or not consent):
                raise WorkspaceError("启用 Live 需要 Key、模型、数据发送确认，且硬离线必须关闭。")
            if provider != self.selected_provider:
                self._auth_epochs[self.selected_provider] += 1
                self.live_enabled = False
            self.selected_provider = provider
            if api_key is not None:
                if api_key != self._keys[provider]:
                    self._auth_epochs[provider] += 1
                self._keys[provider] = api_key
            if model is not None:
                self._models[provider] = model
            if provider == "deepseek" and set_effort:
                self._effort = reasoning_effort
            if acknowledge is not None:
                if not acknowledge or acknowledge != self._acknowledged[provider]:
                    self._auth_epochs[provider] += 1
                self._acknowledged[provider] = acknowledge
            if live_enabled is not None:
                if not live_enabled or live_enabled != self.live_enabled:
                    self._auth_epochs[provider] += 1
                self.live_enabled = live_enabled
            return self.status()

    def clear(self, provider):
        with self._lock:
            self._auth_epochs[provider] += 1
            self._keys[provider] = None
            self._acknowledged[provider] = False
            if provider == self.selected_provider:
                self.live_enabled = False
            return self.status()

    def adapter(self, *, connection_test=False):
        with self._lock:
            name = self.selected_provider
            state = self.status()
            if hard_offline():
                raise WorkspaceError("硬离线已启用，禁止 OpenAI 与 DeepSeek 外部请求。")
            if not connection_test and not state["api_enabled"]:
                raise WorkspaceError("Live 未启用；请在 AI 设置中配置并确认数据发送。")
            credential = self._credential(name)
            key, _ = credential
            epoch = self._auth_epochs[name]
            model = self._model(name)
            if not key or not model:
                raise WorkspaceError("请先配置所选服务的 Key 与模型。")
            options = {"reasoning_effort": self._effort} if name == "deepseek" else {}
            allowed_operation = "connection" if connection_test else "generation"
            def authorized(*, operation=None, begin_send=False):
                with self._lock:
                    current = self.status()
                    valid = (not current["hard_offline"] and current["selected_provider"] == name
                             and self._auth_epochs[name] == epoch and self._credential(name) == credential
                             and operation in {None, allowed_operation}
                             and (connection_test or current["api_enabled"]))
                    if valid and begin_send:
                        # This short critical section orders revocation against SDK entry.
                        # Release the lock before the network request; it may now be in flight.
                        adapter.send_started = True
                    return valid
            adapter = PROVIDERS[name](api_key=key, model=model, explicit_enabled=True,
                                      hard_offline=False, authorization=authorized, **options)
            return adapter

    def close(self):
        with self._lock:
            for name in PROVIDERS:
                self._auth_epochs[name] += 1
            self._keys = {name: None for name in PROVIDERS}
            self._acknowledged = {name: False for name in PROVIDERS}
            self.live_enabled = False
