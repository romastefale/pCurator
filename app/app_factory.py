from aiogram import Dispatcher

from app.routes import ROUTERS


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    for route in ROUTERS:
        dispatcher.include_router(route)
    return dispatcher
