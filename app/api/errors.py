from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.errors import (
    DomainError,
    InsufficientTokensError,
    NoSuitableLegError,
    NotFoundError,
    TooManyActiveTasksError,
)

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    NoSuitableLegError: status.HTTP_400_BAD_REQUEST,
    InsufficientTokensError: status.HTTP_402_PAYMENT_REQUIRED,
    TooManyActiveTasksError: status.HTTP_429_TOO_MANY_REQUESTS,
}


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    code = STATUS_BY_ERROR.get(type(exc), status.HTTP_400_BAD_REQUEST)
    return JSONResponse(status_code=code, content={"detail": str(exc)})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
