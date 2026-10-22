from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.api.schemas import BalanceOut, LedgerEntryOut
from app.container import Container

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}/balance", response_model=BalanceOut)
async def get_balance(user_id: int, container: Container = Depends(get_container)) -> BalanceOut:
    view = await container.payments.balance(user_id)
    return BalanceOut(
        user_id=view.user.id,
        balance=view.user.balance,
        ledger=[LedgerEntryOut.model_validate(entry) for entry in view.entries],
    )
