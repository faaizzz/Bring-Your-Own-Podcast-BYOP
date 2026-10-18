from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="BYOP", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
