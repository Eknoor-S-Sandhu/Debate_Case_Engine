"""Measure stage calls and turn provider failures into safe actionable messages."""

from time import perf_counter

from debate_engine.schemas.diagnostics import InferenceCall

ERROR_MESSAGES = {
    "authentication": "Provider authentication failed. Check the selected provider's API key.",
    "permission": "Provider denied access. Check account permissions and model access.",
    "model_unavailable": "Model unavailable. Check model access for your account.",
    "rate_limit_or_quota": "Provider rate limit or quota reached. Check quota and try later.",
    "invalid_request": "Provider rejected the request/schema. Check model compatibility.",
    "server_error": "Provider service failed. Try again later; no automatic retry was made.",
    "timeout": "Provider request timed out. Try later or adjust the configured timeout.",
    "connection": "Could not connect to the provider. Check network access.",
    "refused": "Provider declined this request; no output was accepted.",
    "incomplete": "Provider output was truncated or incomplete. Check the output-token limit.",
    "malformed": "Provider returned malformed output; no output was accepted.",
    "provider_error": "Provider generation failed; no output was accepted.",
}


def run_inference(provider, result, stage, instructions, context, schema):
    start = perf_counter()
    record = InferenceCall(stage=stage, status="received", elapsed_seconds=0)
    try:
        return provider.generate(instructions, context, schema)
    except Exception as exc:
        # Only our typed errors may contribute diagnostics. Never stringify arbitrary exceptions.
        from debate_engine.agents.strategy_provider import StrategyProviderError

        code = exc.code if isinstance(exc, StrategyProviderError) else "provider_error"
        record.status = "failed"
        record.error_code = code if code in ERROR_MESSAGES else "provider_error"
        record.http_status = exc.http_status if isinstance(exc, StrategyProviderError) else None
        result.warnings.append(ERROR_MESSAGES[record.error_code])
        raise
    finally:
        record.elapsed_seconds = round(perf_counter() - start, 3)
        usage = getattr(provider, "last_usage", {})
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key) if isinstance(usage, dict) else None
            if type(value) is int and value >= 0:
                setattr(record, key, value)
        result.inference_calls.append(record)


def invalid_output(result):
    if result.inference_calls:
        result.inference_calls[-1].status = "invalid_output"
        result.inference_calls[-1].error_code = "validation"
