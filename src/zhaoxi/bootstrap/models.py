"""ZhaoXi models composition."""

from zhaoxi.config.settings import Settings
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.reliability import RetryPolicy


def build_model_runtime(settings: Settings):
    settings.validate_model_config()
    primary_provider = OpenAICompatibleProvider(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        thinking_settings_path=".zhaoxi/model-settings.json",
        timeout=settings.request_timeout_seconds,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
    providers = [primary_provider]
    if settings.model_fallback_name:
        providers.append(OpenAICompatibleProvider(
            base_url=settings.model_fallback_base_url,
            api_key=settings.model_fallback_api_key,
            model=settings.model_fallback_name,
            timeout=settings.request_timeout_seconds,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        ))
    provider = ResilientProvider(
        providers,
        retry_policy=RetryPolicy(
            max_attempts=settings.retry_max_attempts,
            base_delay_seconds=settings.retry_base_delay_seconds,
            max_delay_seconds=settings.retry_max_delay_seconds,
        ),
        failure_threshold=settings.provider_failure_threshold,
        cooldown_seconds=settings.provider_cooldown_seconds,
        max_calls=settings.request_max_model_calls,
        max_total_tokens=settings.request_max_total_tokens,
        budget_policy=settings.request_budget_policy,
    )
    return provider
