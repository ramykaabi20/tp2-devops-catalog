"""Catalog API: microservice REST de catalogue produits.

Endpoints métier : /products (CRUD), /checkout (traitement lent simulé),
/flaky (erreurs intermittentes). Endpoints techniques : /health, /metrics.
"""

import asyncio
import logging
import os
import random
import time

from fastapi import FastAPI, HTTPException, Request, Response
from opentelemetry import trace
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from prometheus_client.openmetrics.exposition import (
    CONTENT_TYPE_LATEST as OPENMETRICS_CONTENT_TYPE,
)
from prometheus_client.openmetrics.exposition import generate_latest as generate_openmetrics
from pydantic import BaseModel, Field

from app.telemetry import current_trace_id, instrument_app, setup_telemetry

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "catalog-api")

logger = logging.getLogger(SERVICE_NAME)
tracer = trace.get_tracer(SERVICE_NAME)

# --- Métriques RED (Rate / Errors / Duration) -------------------------------
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Nombre total de requêtes HTTP",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "Durée de traitement des requêtes HTTP",
    ["method", "route"],
    # 0.2 s est un bucket exact : il sert au SLO de latence (p95 <= 200 ms).
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 2.5, 5.0),
)
UNTRACKED_ROUTES = {"/metrics", "/health"}


# --- Modèle de données -------------------------------------------------------
class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price: float = Field(gt=0)
    stock: int = Field(ge=0)


class Product(ProductIn):
    id: int


class CheckoutItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, le=100)


class Catalog:
    """Stockage en mémoire (suffisant pour le TP, pas de base de données)."""

    def __init__(self) -> None:
        self._items: dict[int, Product] = {}
        self._next_id = 1

    def seed(self) -> None:
        for name, price, stock in [
            ("Clavier mécanique", 89.90, 25),
            ("Souris sans fil", 29.50, 1_000_000),
            ("Écran 27 pouces", 249.00, 8),
        ]:
            self.add(ProductIn(name=name, price=price, stock=stock))

    def add(self, data: ProductIn) -> Product:
        product = Product(id=self._next_id, **data.model_dump())
        self._items[product.id] = product
        self._next_id += 1
        return product

    def get(self, product_id: int) -> Product:
        if product_id not in self._items:
            raise HTTPException(status_code=404, detail="Produit introuvable")
        return self._items[product_id]

    def list(self) -> list[Product]:
        return list(self._items.values())

    def delete(self, product_id: int) -> None:
        self.get(product_id)
        del self._items[product_id]

    def reserve(self, product_id: int, quantity: int) -> Product:
        product = self.get(product_id)
        if quantity > product.stock:
            raise HTTPException(status_code=409, detail="Stock insuffisant")
        product.stock -= quantity
        return product


def _delay_bounds() -> tuple[float, float]:
    low = int(os.getenv("CHECKOUT_MIN_DELAY_MS", "50"))
    high = int(os.getenv("CHECKOUT_MAX_DELAY_MS", "400"))
    if low > high:
        low, high = high, low
    return low / 1000, high / 1000


def _flaky_error_rate() -> float:
    rate = float(os.getenv("FLAKY_ERROR_RATE", "0.1"))
    return min(max(rate, 0.0), 1.0)


# --- Application -------------------------------------------------------------
def create_app() -> FastAPI:
    setup_telemetry(SERVICE_NAME)
    app = FastAPI(title="Catalog API", version=os.getenv("APP_VERSION", "1.0.0"))
    catalog = Catalog()
    catalog.seed()
    app.state.catalog = catalog

    @app.middleware("http")
    async def red_metrics(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path = route.path if route else "unmatched"
            if path not in UNTRACKED_ROUTES:
                elapsed = time.perf_counter() - start
                HTTP_REQUESTS.labels(request.method, path, str(status)).inc()
                trace_id = current_trace_id()
                exemplar = {"trace_id": trace_id} if trace_id else None
                HTTP_DURATION.labels(request.method, path).observe(elapsed, exemplar)
                logger.info(
                    "request",
                    extra={
                        "http_method": request.method,
                        "http_route": path,
                        "http_status": status,
                        "duration_ms": round(elapsed * 1000, 2),
                    },
                )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics(request: Request) -> Response:
        # Prometheus demande OpenMetrics quand les exemplars sont activés.
        if "application/openmetrics-text" in request.headers.get("accept", ""):
            return Response(generate_openmetrics(REGISTRY), media_type=OPENMETRICS_CONTENT_TYPE)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/products", response_model=list[Product])
    def list_products() -> list[Product]:
        return catalog.list()

    @app.get("/products/{product_id}", response_model=Product)
    def get_product(product_id: int) -> Product:
        return catalog.get(product_id)

    @app.post("/products", response_model=Product, status_code=201)
    def create_product(data: ProductIn) -> Product:
        product = catalog.add(data)
        logger.info("product_created", extra={"product_id": product.id})
        return product

    @app.delete("/products/{product_id}", status_code=204)
    def delete_product(product_id: int) -> Response:
        catalog.delete(product_id)
        return Response(status_code=204)

    @app.post("/checkout")
    async def checkout(item: CheckoutItem) -> dict:
        with tracer.start_as_current_span("checkout.process") as span:
            span.set_attribute("catalog.product_id", item.product_id)
            span.set_attribute("catalog.quantity", item.quantity)
            low, high = _delay_bounds()
            with tracer.start_as_current_span("payment.authorize"):
                await asyncio.sleep(random.uniform(low, high))
            product = catalog.reserve(item.product_id, item.quantity)
            total = round(product.price * item.quantity, 2)
            span.set_attribute("catalog.total", total)
            logger.info("checkout_done", extra={"product_id": product.id, "total": total})
            return {"product_id": product.id, "quantity": item.quantity, "total": total}

    @app.get("/flaky")
    def flaky() -> dict:
        if random.random() < _flaky_error_rate():
            logger.error("flaky_failure")
            raise HTTPException(status_code=503, detail="Dépendance indisponible")
        return {"status": "ok"}

    # En dernier : le middleware OpenTelemetry doit envelopper red_metrics
    # pour que les logs et exemplars de la requête portent son trace_id.
    instrument_app(app)
    return app


app = create_app()
