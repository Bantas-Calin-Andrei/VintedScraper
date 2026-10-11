"""Dashboard: one page, htmx fragments, settings panel, Excel download. Local only (127.0.0.1)."""
from __future__ import annotations

import io
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Callable

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import db, stats
from ..brand_lookup import BrandLookup
from ..export import build_report, write_report
from ..models import utcnow
from ..vinted_ref import PRODUCT_TYPES

HERE = Path(__file__).resolve().parent
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STATUS_FILTERS = tuple(stats.STATUS_LABELS.items())
ConnFactory = Callable[[], AbstractContextManager[psycopg.Connection]]


def create_app(
    conn_factory: ConnFactory,
    lookup: BrandLookup,
    *,
    base_url: str = "https://www.vinted.ro",
    clock: Callable[[], datetime] = utcnow,
) -> FastAPI:
    app = FastAPI(title="Vinted tracker", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")

    def render(request: Request, name: str, **context) -> HTMLResponse:
        return templates.TemplateResponse(request, name, context)

    @app.get("/", response_class=HTMLResponse)
    def page(request: Request):
        try:
            with conn_factory() as conn:
                brands = stats.distinct_brands(conn)
        except psycopg.OperationalError:
            brands = []
        return render(request, "page.html", brands=brands, types=list(PRODUCT_TYPES.items()), statuses=STATUS_FILTERS)

    @app.get("/fragments/status", response_class=HTMLResponse)
    def status_fragment(request: Request):
        try:
            with conn_factory() as conn:
                row = db.get_tracker_status(conn)
        except psycopg.OperationalError:
            return render(request, "_db_error.html")
        return render(request, "_status.html", state=stats.tracker_state(row, clock()))

    @app.get("/fragments/tiles", response_class=HTMLResponse)
    def tiles_fragment(request: Request):
        try:
            with conn_factory() as conn:
                tiles = stats.tiles(conn, clock())
        except psycopg.OperationalError:
            return render(request, "_db_error.html")
        return render(request, "_tiles.html", t=tiles)

    @app.get("/api/charts")
    def charts():
        try:
            with conn_factory() as conn:
                return stats.chart_series(conn)
        except psycopg.OperationalError:
            return JSONResponse({}, status_code=503)

    @app.get("/fragments/products", response_class=HTMLResponse)
    def products_fragment(request: Request, status: str = "", brand: str = "", type: str = "", q: str = "", page: int = 1):
        type_id = int(type) if type.isdigit() else None
        try:
            with conn_factory() as conn:
                rows, total = stats.products(conn, clock(), status=status, brand=brand, type_id=type_id, q=q,
                                             page=page, base_url=base_url)
        except psycopg.OperationalError:
            return render(request, "_db_error.html")
        pages = max(1, -(-total // stats.PAGE_SIZE))
        return render(request, "_products.html", rows=rows, total=total, page=min(page, pages), pages=pages)

    @app.get("/export.xlsx")
    def export():
        try:
            with conn_factory() as conn:
                frames = build_report(conn, base_url)
        except psycopg.OperationalError:
            return Response("Can't reach the database.", status_code=503, media_type="text/plain")
        buffer = io.BytesIO()
        write_report(frames, buffer)
        name = f"vinted_report_{clock().date().isoformat()}.xlsx"
        return Response(buffer.getvalue(), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    return app
