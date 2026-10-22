from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ValidationError

from app.container import Container
from app.core.security import SIGNATURE_HEADER, is_valid_signature

M = TypeVar("M", bound=BaseModel)


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


async def read_signed_body(request: Request, schema: type[M]) -> M:
    body = await request.body()
    secret = get_container(request).settings.webhook_secret
    if not is_valid_signature(body, request.headers.get(SIGNATURE_HEADER), secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid signature")
    try:
        return schema.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.errors(include_url=False)) from exc
