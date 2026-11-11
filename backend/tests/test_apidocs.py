"""Documentación OpenAPI de la API externa (API key): alcance, acceso solo con sesión y Swagger UI empaquetada."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import docs as apidocs
from app.core import settings
from app.api.auth import Auth
from app.main import create_app

PW = "correct horse"
HOOK_PATHS = {"/api/hook/ping", "/api/hook/watches", "/api/hook/{game}/opened"}
ASSET_BODIES = {
    "swagger-ui-bundle.js": b"/* bundle */",
    "swagger-ui.css": b"/* css */",
    "favicon-32x32.png": b"\x89PNG",
}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config" / "config.yaml")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static" / "docs-assets").mkdir(parents=True)
    (tmp_path / "static" / "index.html").write_text("<html>SPA</html>")
    for n, b in ASSET_BODIES.items():
        (tmp_path / "static" / "docs-assets" / n).write_bytes(b)
    return create_app(Auth("admin", PW, 1, rounds=4))


@pytest.fixture
def anon(app):
    return TestClient(app)


@pytest.fixture
def client(app):
    c = TestClient(app)
    assert c.post("/api/login", json={"user": "admin", "password": PW}).status_code == 200
    return c


def code(r):
    return r.json()["detail"]["code"]


def test_openapi_requires_session(anon):
    r = anon.get("/api/openapi.json")
    assert r.status_code == 401 and code(r) == "err.main.session_required"


def test_api_key_alone_does_not_open_docs(client, anon):
    key = client.post("/api/profile/apikey").json()["key"]
    hdr = {"Authorization": f"Bearer {key}"}
    for url in ("/api/openapi.json", "/api/docs", "/api/docs-assets/swagger-ui.css"):
        r = anon.get(url, headers=hdr)
        assert r.status_code == 401 and code(r) == "err.main.session_required", url


def test_openapi_only_has_the_three_hook_paths(client):
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    j = r.json()
    assert set(j["paths"]) == HOOK_PATHS
    assert {(p, m) for p, v in j["paths"].items() for m in v} == {
        ("/api/hook/ping", "get"),
        ("/api/hook/watches", "get"),
        ("/api/hook/{game}/opened", "post"),
    }
    assert j["info"]["title"] == "API de Checkpoint (avisos del lanzador)"
    assert j["info"]["version"] == (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
    assert [t["name"] for t in j["tags"]] == [apidocs.TAG]
    assert all(op["tags"] == [apidocs.TAG] for v in j["paths"].values() for op in v.values())


def test_openapi_security_scheme_and_errors(client):
    j = client.get("/api/openapi.json").json()
    schemes = j["components"]["securitySchemes"]
    assert (
        list(schemes) == ["bearerAuth"]
        and schemes["bearerAuth"]["type"] == "http"
        and schemes["bearerAuth"]["scheme"] == "bearer"
    )
    assert "ErrorBody" in j["components"]["schemas"]
    assert "HTTPValidationError" not in j["components"]["schemas"]
    for v in j["paths"].values():
        for op in v.values():
            assert op["security"] == [{"bearerAuth": []}]
            assert "422" not in op["responses"]
            assert "401" in op["responses"] and "429" in op["responses"]
            assert (
                "Retry-After" in op["responses"]["429"]["headers"]
                and "WWW-Authenticate" in op["responses"]["401"]["headers"]
            )
    opened = j["paths"]["/api/hook/{game}/opened"]["post"]
    assert {"200", "400", "404", "409"} <= set(opened["responses"])
    assert "sincronización previa real" in opened["description"] and "arma el vigilante" in opened["description"]
    assert {p["name"]: p["in"] for p in opened["parameters"]} == {"game": "path", "device": "query"}


def test_docs_page_needs_session_and_is_self_contained(client, anon):
    r = anon.get("/api/docs")
    assert r.status_code == 401 and code(r) == "err.main.session_required"
    r = client.get("/api/docs")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    for cdn in ("jsdelivr", "unpkg", "cdnjs", "http://", "https://"):
        assert cdn not in html, cdn
    assert "/api/openapi.json" in html and '"supportedSubmitMethods": ["get", "post"]' in html
    assert "SPA" not in html  # no lo sirve el catch-all


def test_docs_assets_served_locally(client, anon):
    for n, body in ASSET_BODIES.items():
        r = client.get(f"/api/docs-assets/{n}")
        assert r.status_code == 200 and r.content == body, n
        assert f"/api/docs-assets/{n}" in client.get("/api/docs").text
        assert anon.get(f"/api/docs-assets/{n}").status_code == 401


def test_docs_assets_closed_list_and_missing_build(client, tmp_path):
    assert client.get("/api/docs-assets/LICENSE").status_code == 404
    assert client.get("/api/docs-assets/..%2Findex.html").status_code == 404
    (tmp_path / "static" / "docs-assets" / "swagger-ui.css").unlink()
    assert client.get("/api/docs-assets/swagger-ui.css").status_code == 404


def test_catch_all_does_not_swallow_docs_and_unknown_api_is_404(client):
    assert client.get("/api/docs").text != client.get("/cualquier-cosa").text
    assert client.get("/cualquier-cosa").text == "<html>SPA</html>"
    r = client.get("/api/docs/otra")
    assert r.status_code == 404 and code(r) == "err.main.not_found"


def test_every_api_route_is_public_tag_or_hidden(app):
    """Deriva: una ruta /api/* nueva debe quedar oculta del esquema o ser del tag público (y entonces es una de las 3)."""
    public = set()
    for r in apidocs.iter_api_routes(app.routes):
        path = r.path
        if not path.startswith("/api/"):
            continue
        in_public = apidocs.TAG in (r.tags or [])
        assert in_public or not r.include_in_schema, (
            f"{r.methods} {path}: ni en el tag público ni include_in_schema=False"
        )
        if in_public:
            assert r.include_in_schema and path.startswith(apidocs.API_PREFIX), path
            public.add(path)
    assert public == HOOK_PATHS
    assert (
        len([r for r in apidocs.iter_api_routes(app.routes) if r.path.startswith("/api/")]) > 30
    )  # el recorrido no se queda corto
    # Los routers van anidados (`include_router`): el catch-all SPA es la última de todas las rutas aplanadas, y oculta.
    flat = list(apidocs.iter_api_routes(app.routes))
    spa = [r for r in flat if r.path == "/{path:path}"]
    assert spa and not spa[0].include_in_schema
    assert flat[-1] is spa[0]


def test_new_internal_router_endpoint_is_hidden_by_default():
    """Los routers nuevos (`internal_router`/`public_router`) nacen ocultos del Swagger sin hacer nada más."""
    from app.api.deps import internal_router, public_router

    for make in (internal_router, public_router):
        router = make()

        @router.get("/api/nuevo")
        def nuevo():
            return {}

        assert [r.include_in_schema for r in router.routes] == [False]
