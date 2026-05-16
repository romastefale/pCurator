from app.callbacks import router as callback_router
from app.commands import router as commands_router
from app.edit_flow import router as edit_router
from app.link_flow import router as link_router

ROUTERS = (commands_router, edit_router, link_router, callback_router)
