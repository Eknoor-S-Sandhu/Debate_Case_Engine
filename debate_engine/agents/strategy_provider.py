"""Explicit provider selection; bounded requests without retries or fallback."""

import copy
import json
import shutil
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from debate_engine.config import CodexCLISettings, InferenceProviderSettings, Settings


class StrategyProviderError(RuntimeError):
    def __init__(self, message, *, code="provider_error", http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def provider_settings(
    settings: Settings, name: str | None = None
) -> InferenceProviderSettings | CodexCLISettings:
    name = name or settings.strategy.provider
    if name not in {"openai", "anthropic", "gemini", "codex_cli"}:
        raise ValueError("Unsupported inference provider.")
    config = getattr(settings, name).model_copy(deep=True)
    if name == "openai":
        # Old OpenAI-only environments remain usable. Never reuse this key for other hosts.
        if config.api_key is None:
            config.api_key = settings.strategy.api_key
        if config.model is None:
            config.model = settings.strategy.model
    return config


def remote_allowed(
    settings: Settings, config: InferenceProviderSettings | CodexCLISettings
) -> bool:
    return settings.strategy.allow_remote if config.allow_remote is None else config.allow_remote


def inference_ready(settings: Settings) -> bool:
    config = provider_settings(settings)
    if settings.strategy.provider == "codex_cli":
        return remote_allowed(settings, config) and shutil.which(config.executable) is not None
    return bool(
        remote_allowed(settings, config)
        and config.api_key is not None
        and config.api_key.get_secret_value().strip()
        and config.model
    )


def inference_metadata(settings: Settings, injected=False) -> dict:
    return {
        "provider": "injected" if injected else settings.strategy.provider,
        "model": None if injected else provider_settings(settings).model,
    }


def anthropic_schema(schema: dict) -> dict:
    """Relax unsupported grammar constraints while retaining them in descriptions.

    The agents always validate against the original Pydantic contract afterward.
    """
    node = copy.deepcopy(schema)
    unsupported = {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "maxItems",
    }

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            constraints = []
            for key in list(value):
                if key in unsupported or (key == "minItems" and value[key] > 1):
                    constraints.append(f"{key}={value.pop(key)}")
            if constraints:
                value["description"] = (
                    value.get("description", "")
                    + " Required constraints: "
                    + ", ".join(constraints)
                ).strip()
            for child in value.values():
                visit(child)

    visit(node)
    return node


def gemini_schema(schema: dict) -> dict:
    """Avoid expensive bounded grammar states; agents enforce original bounds locally."""
    return anthropic_schema(schema)


def request_json(settings, url, headers, payload):
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with build_opener(NoRedirects()).open(
            request, timeout=settings.strategy.timeout_seconds
        ) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise StrategyProviderError("Inference response exceeded the size limit.")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise StrategyProviderError("Inference response was malformed.")
        return result
    except StrategyProviderError:
        raise
    except HTTPError as exc:
        code = {
            400: "invalid_request",
            401: "authentication",
            403: "permission",
            404: "model_unavailable",
            429: "rate_limit_or_quota",
        }.get(exc.code, "server_error" if exc.code >= 500 else "provider_error")
        raise StrategyProviderError(
            f"Inference provider HTTP error {exc.code}.", code=code, http_status=exc.code
        ) from None
    except (TimeoutError, URLError) as exc:
        timed_out = isinstance(exc, TimeoutError) or isinstance(
            getattr(exc, "reason", None), TimeoutError
        )
        raise StrategyProviderError(
            "Inference connection failed.", code="timeout" if timed_out else "connection"
        ) from None
    except Exception:
        raise StrategyProviderError(
            "Inference request failed; check configuration and connection."
        ) from None


class BaseProvider:
    name = ""

    def __init__(self, settings: Settings):
        self.settings = settings.model_copy(deep=True)
        self.config = provider_settings(self.settings, self.name)
        self.last_usage = {}

    def generate(self, instructions: str, context: str, schema: dict) -> dict:
        self.last_usage = {}
        if (
            not remote_allowed(self.settings, self.config)
            or self.config.api_key is None
            or not self.config.api_key.get_secret_value().strip()
            or not self.config.model
        ):
            raise StrategyProviderError("Inference provider is not configured.")
        if len(context) > self.settings.strategy.max_input_characters:
            raise StrategyProviderError("Inference input exceeds the configured size limit.")
        try:
            text = self.generate_text(instructions, context, schema)
            result = json.loads(text)
            if not isinstance(result, dict):
                raise ValueError("Expected an object.")
            return result
        except StrategyProviderError:
            raise
        except Exception:
            raise StrategyProviderError(
                "Inference output was malformed or incomplete.", code="malformed"
            ) from None


class OpenAIStrategyProvider(BaseProvider):
    name = "openai"

    def generate_text(self, instructions, context, schema):
        result = request_json(
            self.settings,
            "https://api.openai.com/v1/responses",
            {"Authorization": f"Bearer {self.config.api_key.get_secret_value()}"},
            {
                "model": self.config.model,
                "instructions": instructions,
                "input": context,
                "store": False,
                "max_output_tokens": self.settings.strategy.max_output_tokens,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "debate_architectures",
                        "strict": True,
                        "schema": schema,
                    }
                },
            },
        )
        self.last_usage = normalized_usage(result, self.name)
        if result.get("status") != "completed":
            raise StrategyProviderError(
                "OpenAI response was incomplete or failed.", code="incomplete"
            )
        texts = []
        for item in result.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "refusal":
                    raise StrategyProviderError("OpenAI refused generation.", code="refused")
                if content.get("type") == "output_text":
                    texts.append(content["text"])
        return "".join(texts)


class AnthropicStrategyProvider(BaseProvider):
    name = "anthropic"

    def generate_text(self, instructions, context, schema):
        result = request_json(
            self.settings,
            "https://api.anthropic.com/v1/messages",
            {
                "x-api-key": self.config.api_key.get_secret_value(),
                "anthropic-version": "2023-06-01",
            },
            {
                "model": self.config.model,
                "system": instructions,
                "max_tokens": self.settings.strategy.max_output_tokens,
                "messages": [{"role": "user", "content": context}],
                "output_config": {
                    "format": {"type": "json_schema", "schema": anthropic_schema(schema)}
                },
            },
        )
        self.last_usage = normalized_usage(result, self.name)
        if result.get("stop_reason") == "refusal":
            raise StrategyProviderError("Anthropic refused generation.", code="refused")
        if result.get("stop_reason") != "end_turn":
            raise StrategyProviderError(
                "Anthropic response was refused, incomplete or failed.", code="incomplete"
            )
        blocks = result.get("content", [])
        if any(block.get("type") != "text" for block in blocks):
            raise StrategyProviderError("Anthropic returned unexpected content.")
        return "".join(block["text"] for block in blocks)


class GeminiStrategyProvider(BaseProvider):
    name = "gemini"

    def generate_text(self, instructions, context, schema):
        model = quote(self.config.model.removeprefix("models/"), safe="")
        result = request_json(
            self.settings,
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {"x-goog-api-key": self.config.api_key.get_secret_value()},
            {
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"role": "user", "parts": [{"text": context}]}],
                "generationConfig": {
                    "maxOutputTokens": self.settings.strategy.max_output_tokens,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": gemini_schema(schema),
                },
            },
        )
        self.last_usage = normalized_usage(result, self.name)
        if result.get("promptFeedback", {}).get("blockReason"):
            raise StrategyProviderError("Gemini blocked the request.", code="refused")
        candidates = result.get("candidates", [])
        if len(candidates) != 1 or candidates[0].get("finishReason") != "STOP":
            raise StrategyProviderError(
                "Gemini response was blocked, incomplete or failed.", code="incomplete"
            )
        parts = candidates[0].get("content", {}).get("parts", [])
        if any("text" not in part for part in parts):
            raise StrategyProviderError("Gemini returned unexpected content.")
        return "".join(part["text"] for part in parts if not part.get("thought", False))


def create_provider(settings: Settings):
    if settings.strategy.provider == "codex_cli":
        from debate_engine.agents.codex_cli_provider import CodexCLIProvider

        return CodexCLIProvider(settings)
    providers = {
        "openai": OpenAIStrategyProvider,
        "anthropic": AnthropicStrategyProvider,
        "gemini": GeminiStrategyProvider,
    }
    return providers[settings.strategy.provider](settings)


def normalized_usage(response, name):
    usage = response.get("usageMetadata" if name == "gemini" else "usage", {})
    if not isinstance(usage, dict):
        return {}
    keys = (
        ("promptTokenCount", "candidatesTokenCount", "totalTokenCount")
        if name == "gemini"
        else ("input_tokens", "output_tokens", "total_tokens")
    )
    return {
        target: usage.get(source)
        for target, source in zip(
            ("input_tokens", "output_tokens", "total_tokens"), keys, strict=True
        )
    }
