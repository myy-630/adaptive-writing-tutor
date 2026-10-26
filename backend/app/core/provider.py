from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.core.errors import ProviderUnavailable

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class ModelProvider(Protocol):
    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type[ResponseT]
    ) -> ResponseT: ...


class UnconfiguredModelProvider:
    async def generate_structured(
        self, *, system_prompt: str, user_prompt: str, response_type: type[ResponseT]
    ) -> ResponseT:
        raise ProviderUnavailable()
