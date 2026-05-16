from aiogram import Dispatcher

from app.routes import ROUTERS


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    return dispatcher
