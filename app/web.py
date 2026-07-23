from fastapi import FastAPI


def create_web_app() -> FastAPI:
    app = FastAPI(title="PlagiAI Health", docs_url=None, redoc_url=None)

    @app.get("/")
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "PlagiAI Bot",
            "provider": "Quetext",
        }

    return app
