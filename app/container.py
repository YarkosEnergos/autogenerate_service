from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.providers import ProviderGateway
from app.core.config import Settings
from app.services.dispatcher import Dispatcher
from app.services.payments import PaymentService
from app.services.tasks import TaskService
from app.services.watchdog import Watchdog


class Container:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: ProviderGateway,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.gateway = gateway
        self.payments = PaymentService(session_factory, settings.ledger_history_limit)
        self.tasks = TaskService(session_factory, settings)
        self.dispatcher = Dispatcher(self.tasks, gateway)
        self.watchdog = Watchdog(self.tasks, self.dispatcher, settings.watchdog_interval)
