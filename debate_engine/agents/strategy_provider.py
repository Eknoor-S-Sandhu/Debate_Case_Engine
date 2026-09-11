"""Explicitly configured OpenAI Responses adapter with no tools or retries."""

import json
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from debate_engine.config import Settings


class StrategyProviderError(RuntimeError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenAIStrategyProvider:
    def __init__(self, settings: Settings):
        self.config = settings.strategy

    def generate(self, instructions: str, context: str, schema: dict) -> dict:
        config = self.config
        if not config.allow_remote or config.api_key is None or not config.model:
            raise StrategyProviderError("Strategy model is not configured.")
        payload = {
            "model": config.model,
            "instructions": instructions,
            "input": context,
            "store": False,
            "max_output_tokens": config.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "debate_architectures",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key.get_secret_value()}",
            },
            method="POST",
        )
        try:
            with build_opener(NoRedirects()).open(
                request, timeout=config.timeout_seconds
            ) as response:
                body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise StrategyProviderError("Strategy response exceeded the size limit.")
            result = json.loads(body)
            if result.get("status") != "completed":
                raise StrategyProviderError("Strategy response was incomplete or failed.")
            texts = []
            for item in result.get("output", []):
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") == "refusal":
                        raise StrategyProviderError("The model declined strategy generation.")
                    if content.get("type") == "output_text":
                        texts.append(content["text"])
            if not texts:
                raise StrategyProviderError("Strategy response contained no output.")
            return json.loads("".join(texts))
        except StrategyProviderError:
            raise
        except HTTPError as exc:
            raise StrategyProviderError(f"Strategy provider HTTP error {exc.code}.") from None
        except Exception:
            raise StrategyProviderError(
                "Strategy request failed; check configuration and connection."
            ) from None
