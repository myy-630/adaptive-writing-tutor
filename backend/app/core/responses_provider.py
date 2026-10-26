from typing import Any

from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, SecretStr

from app.core.config import Settings
from app.core.errors import DomainError, ProviderUnavailable
from app.core.provider import ResponseT


class ResponsesModelProvider:
    """Structured-output adapter for an OpenAI-compatible Responses endpoint."""

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        model: str,
        base_url: str | None = None,
        client: AsyncOpenAI | Any | None = None,
    ) -> None:
        if api_key is None or not api_key.get_secret_value():
            raise ProviderUnavailable()
        self.model = model
        self.client = client or AsyncOpenAI(api_key=api_key.get_secret_value(), base_url=base_url)

    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type[ResponseT]
    ) -> ResponseT:
        try:
            response = await self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=response_type,
                store=False,
            )
        except APIError as exc:
            raise DomainError("model_generation_failed", "Model generation failed", 503) from exc
        parsed = response.output_parsed
        if parsed is None:
            raise DomainError("model_output_missing", "Model returned no structured output", 502)
        if not isinstance(parsed, BaseModel):
            raise DomainError("model_output_invalid", "Model output did not match schema", 502)
        return response_type.model_validate(parsed)

    async def aclose(self) -> None:
        await self.client.close()


def configured_responses_provider(settings: Settings) -> ResponsesModelProvider | None:
    if settings.model_provider == "deepseek":
        if settings.deepseek_api_key is None:
            return None
        return ResponsesModelProvider(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            base_url="https://api.deepseek.com",
        )
    if settings.openai_api_key is None:
        return None
    return ResponsesModelProvider(api_key=settings.openai_api_key, model=settings.openai_model)
