from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.control_plane_routes import router as control_plane_router
from routes.message_routes import router as message_router


def create_app() -> FastAPI:
    """FastAPI entrypoint. Keep this file thin and let modules do the work."""
    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(control_plane_router)
    app.include_router(message_router)
    return app


app = create_app()
