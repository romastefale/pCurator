from app.callbacks import router as callback_router
from app.commands import router as commands_router
from app.edit_flow import router as edit_router
from app.image_flow import router as image_router
from app.link_flow import router as link_router
from app.membership import router as membership_router
from app.mira_flow import router as mira_router
from app.published import router as published_router
from app.reaction_tools import router as reaction_tools_router

ROUTERS = (
    commands_router,
    reaction_tools_router,
    mira_router,
    link_router,
    image_router,
    edit_router,
    published_router,
    callback_router,
    membership_router,
)
