import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import main, telemetry


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CHECKOUT_MIN_DELAY_MS", "0")
    monkeypatch.setenv("CHECKOUT_MAX_DELAY_MS", "1")
    return TestClient(main.create_app())


# --- Cas nominaux ------------------------------------------------------------
def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_list_products_is_seeded(client):
    products = client.get("/products").json()
    assert len(products) == 3
    assert {"id", "name", "price", "stock"} <= products[0].keys()


def test_get_product(client):
    response = client.get("/products/1")
    assert response.status_code == 200
    assert response.json()["id"] == 1


def test_create_then_delete_product(client):
    created = client.post("/products", json={"name": "Webcam", "price": 59.9, "stock": 4})
    assert created.status_code == 201
    new_id = created.json()["id"]
    assert new_id == 4
    assert client.delete(f"/products/{new_id}").status_code == 204
    assert client.get(f"/products/{new_id}").status_code == 404


def test_checkout_reserves_stock_and_computes_total(client):
    response = client.post("/checkout", json={"product_id": 2, "quantity": 3})
    assert response.status_code == 200
    assert response.json() == {"product_id": 2, "quantity": 3, "total": 88.5}
    assert client.get("/products/2").json()["stock"] == 999_997


def test_flaky_success(client, monkeypatch):
    monkeypatch.setenv("FLAKY_ERROR_RATE", "0")
    assert client.get("/flaky").status_code == 200


def test_flaky_failure(client, monkeypatch):
    monkeypatch.setenv("FLAKY_ERROR_RATE", "1")
    response = client.get("/flaky")
    assert response.status_code == 503


# --- Cas aux limites (edge cases) ------------------------------------------------
def test_unknown_product_returns_404(client):
    assert client.get("/products/999").status_code == 404
    assert client.delete("/products/999").status_code == 404


def test_non_integer_id_returns_422(client):
    assert client.get("/products/abc").status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "price": 10, "stock": 1},
        {"name": "X", "price": 0, "stock": 1},
        {"name": "X", "price": -5, "stock": 1},
        {"name": "X", "price": 10, "stock": -1},
        {"name": "X" * 101, "price": 10, "stock": 1},
        {"price": 10, "stock": 1},
    ],
)
def test_invalid_product_is_rejected(client, payload):
    assert client.post("/products", json=payload).status_code == 422


def test_checkout_whole_stock_then_out_of_stock(client):
    stock = client.get("/products/3").json()["stock"]
    assert client.post("/checkout", json={"product_id": 3, "quantity": stock}).status_code == 200
    assert client.get("/products/3").json()["stock"] == 0
    response = client.post("/checkout", json={"product_id": 3, "quantity": 1})
    assert response.status_code == 409


@pytest.mark.parametrize("quantity", [0, -1, 101])
def test_checkout_invalid_quantity(client, quantity):
    response = client.post("/checkout", json={"product_id": 1, "quantity": quantity})
    assert response.status_code == 422


def test_checkout_unknown_product(client):
    assert client.post("/checkout", json={"product_id": 42, "quantity": 1}).status_code == 404


def test_delay_bounds_are_swapped_when_inverted(monkeypatch):
    monkeypatch.setenv("CHECKOUT_MIN_DELAY_MS", "300")
    monkeypatch.setenv("CHECKOUT_MAX_DELAY_MS", "100")
    assert main._delay_bounds() == (0.1, 0.3)


@pytest.mark.parametrize("raw,expected", [("-1", 0.0), ("0.25", 0.25), ("7", 1.0)])
def test_flaky_rate_is_clamped(monkeypatch, raw, expected):
    monkeypatch.setenv("FLAKY_ERROR_RATE", raw)
    assert main._flaky_error_rate() == expected


def test_unmatched_route_is_counted(client):
    assert client.get("/does-not-exist").status_code == 404
    body = client.get("/metrics").text
    assert 'route="unmatched",status="404"' in body


# --- Observabilité -----------------------------------------------------------
def test_metrics_exposes_red_metrics(client):
    client.get("/products")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'http_requests_total{method="GET",route="/products",status="200"}' in response.text
    assert 'http_request_duration_seconds_bucket{le="0.2",method="GET",route="/products"}' in (
        response.text
    )
    assert "/metrics" not in response.text.split("route=")[-1]


def test_metrics_openmetrics_format(client):
    client.get("/products")
    response = client.get("/metrics", headers={"Accept": "application/openmetrics-text"})
    assert response.headers["content-type"].startswith("application/openmetrics-text")
    assert response.text.rstrip().endswith("# EOF")


def test_server_errors_are_counted_as_5xx(client, monkeypatch):
    monkeypatch.setenv("FLAKY_ERROR_RATE", "1")
    client.get("/flaky")
    assert 'route="/flaky",status="503"' in client.get("/metrics").text


def test_json_formatter_includes_trace_context():
    tracer = telemetry.trace.get_tracer("test")
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", (), None)
    record.order_id = 7
    with tracer.start_as_current_span("span"):
        payload = json.loads(telemetry.JsonFormatter().format(record))
        expected_trace = telemetry.current_trace_id()
    assert payload["message"] == "hello"
    assert payload["order_id"] == 7
    assert payload["trace_id"] == expected_trace and len(expected_trace) == 32
    assert len(payload["span_id"]) == 16


def test_json_formatter_without_span_and_with_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "err", (), sys.exc_info())
    payload = json.loads(telemetry.JsonFormatter().format(record))
    assert "trace_id" not in payload
    assert "ValueError: boom" in payload["exception"]
    assert telemetry.current_trace_id() is None


def test_otlp_export_is_enabled_with_endpoint(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    root_handlers = list(logging.getLogger().handlers)
    telemetry._enable_otlp_export(provider, provider.resource, "http://collector:4318/")
    processors = provider._active_span_processor._span_processors
    assert processors[0].span_exporter._endpoint == "http://collector:4318/v1/traces"
    assert len(logging.getLogger().handlers) == len(root_handlers) + 1
    logging.getLogger().handlers = root_handlers
    provider.shutdown()


def test_setup_telemetry_is_idempotent(monkeypatch):
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    calls = []
    monkeypatch.setattr(telemetry, "_enable_otlp_export", lambda *a: calls.append(a))
    telemetry.setup_telemetry("svc")
    telemetry.setup_telemetry("svc")
    assert len(calls) == 1


def test_request_log_carries_trace_id(client):
    lines = []

    class Capture(logging.Handler):
        def emit(self, record):
            lines.append(json.loads(telemetry.JsonFormatter().format(record)))

    handler = Capture()
    logger = logging.getLogger("catalog-api")
    logger.addHandler(handler)
    try:
        client.get("/products")
    finally:
        logger.removeHandler(handler)
    request_log = next(line for line in lines if line["message"] == "request")
    assert request_log["http_route"] == "/products"
    assert request_log["http_status"] == 200
    assert len(request_log["trace_id"]) == 32
