"""Documentación OpenAPI de la API externa (API key): alcance, acceso solo con sesión y Swagger UI empaquetada."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import docs as apidocs
from app.core import settings
from app.api.auth import Auth
from app.main import create_app

PW = "correct horse"
HOOK_PATHS = {
    "/api/hook/ping",
    "/api/hook/watches",
    "/api/hook/{game}/opened",
    "/api/hook/{game}/fingerprint",
    "/api/hook/{game}/closed",
    "/api/hook/{game}/manifest",
    "/api/hook/{game}/files",
    "/api/hook/{game}/commit",
    "/api/games",
}
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


def test_openapi_only_has_the_api_key_paths(client):
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    j = r.json()
    assert set(j["paths"]) == HOOK_PATHS
    assert {(p, m) for p, v in j["paths"].items() for m in v} == {
        ("/api/hook/ping", "get"),
        ("/api/hook/watches", "get"),
        ("/api/hook/{game}/opened", "post"),
        ("/api/hook/{game}/fingerprint", "post"),
        ("/api/hook/{game}/closed", "post"),
        ("/api/hook/{game}/manifest", "get"),
        ("/api/hook/{game}/files", "get"),
        ("/api/hook/{game}/files", "put"),
        ("/api/hook/{game}/commit", "post"),
        ("/api/games", "get"),
    }
    assert j["info"]["title"] == "API de Checkpoint (avisos del lanzador)"
    assert j["info"]["version"] == (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
    assert [t["name"] for t in j["tags"]] == [apidocs.TAG, apidocs.GAMES_TAG]
    assert {p: [op["tags"] for op in v.values()] for p, v in j["paths"].items()} == {
        **{p: [[apidocs.TAG]] for p in HOOK_PATHS - {"/api/games", "/api/hook/{game}/files"}},
        "/api/hook/{game}/files": [[apidocs.TAG], [apidocs.TAG]],  # GET (bajada) y PUT (subida)
        "/api/games": [[apidocs.GAMES_TAG]],
    }


SECURITY_BY_KIND = {
    "user": [{"bearerAuth": []}],
    "device": [{"deviceKeyAuth": []}],
    "any": [{"bearerAuth": []}, {"deviceKeyAuth": []}],
}


def test_key_matrix_documented_exactly():
    assert apidocs.KEY_KINDS == {
        "/api/hook/ping": "any",
        "/api/hook/watches": "user",
        "/api/hook/{game}/opened": "user",
        "/api/hook/{game}/closed": "device",
        "/api/hook/{game}/fingerprint": "device",
        "/api/hook/{game}/manifest": "device",
        "/api/hook/{game}/files": "device",
        "/api/hook/{game}/commit": "device",
        "/api/games": "any",
    }
    assert set(apidocs.KEY_KINDS) == HOOK_PATHS


def test_openapi_security_scheme_and_errors(client):
    j = client.get("/api/openapi.json").json()
    schemes = j["components"]["securitySchemes"]
    assert list(schemes) == ["bearerAuth", "deviceKeyAuth"]  # dos clases de key: usuario (ck_) y dispositivo (ckd_)
    assert all(v["type"] == "http" and v["scheme"] == "bearer" for v in schemes.values())
    assert "ck_" in schemes["bearerAuth"]["bearerFormat"] and "ckd_" in schemes["deviceKeyAuth"]["bearerFormat"]
    assert "ckd_" in j["info"]["description"] and "dos clases de key" in j["info"]["description"]
    assert "ErrorBody" in j["components"]["schemas"]
    assert "HTTPValidationError" not in j["components"]["schemas"]
    for path, v in j["paths"].items():
        for op in v.values():
            assert op["security"] == SECURITY_BY_KIND[apidocs.KEY_KINDS[path]]
            assert "**Key aceptada:**" in op["description"]
            assert (
                op["responses"].get("422", {}).get("description") != "Validation Error"
            )  # nunca el genérico de FastAPI
            assert "401" in op["responses"] and "429" in op["responses"]
            assert (
                "Retry-After" in op["responses"]["429"]["headers"]
                and "WWW-Authenticate" in op["responses"]["401"]["headers"]
            )
    games = j["paths"]["/api/games"]["get"]
    assert games["summary"] and "200" in games["responses"]
    ok = games["responses"]["200"]["content"]["application/json"]
    assert ok["schema"]["items"]["$ref"].endswith("/GameItem") and ok["examples"]["games"]["value"][0]["id"] == "g1"
    ex = ok["examples"]["games"]["value"]
    assert (
        ex[0]["steam_appid"] == 1245620 and ex[1].get("steam_appid") is None
    )  # con y sin appid (OpenAPI omite los null)
    item = j["components"]["schemas"]["GameItem"]["properties"]["steam_appid"]
    assert {"type": "integer"} in item["anyOf"] and {"type": "null"} in item["anyOf"] and item["description"]
    assert {"GameItem", "GameSyncStatus"} <= set(j["components"]["schemas"])
    opened = j["paths"]["/api/hook/{game}/opened"]["post"]
    assert {"200", "400", "404", "409"} <= set(opened["responses"])
    assert "sincronización previa real" in opened["description"] and "arma el vigilante" in opened["description"]
    assert {p["name"]: p["in"] for p in opened["parameters"]} == {"game": "path", "device": "query"}


def test_openapi_closed_operation(client):
    j = client.get("/api/openapi.json").json()
    op = j["paths"]["/api/hook/{game}/closed"]["post"]
    assert op["tags"] == [apidocs.TAG] and op["summary"] and op["security"] == [{"deviceKeyAuth": []}]
    assert {"200", "401", "403", "404", "409", "429"} <= set(op["responses"]) and "requestBody" not in op
    assert {p["name"]: p["in"] for p in op["parameters"]} == {"game": "path", "device": "query"}
    ok = op["responses"]["200"]["content"]["application/json"]
    assert ok["schema"]["$ref"].endswith("/ClosedResult") and set(ok["examples"]) == {"ok", "disabled"}
    assert "ClosedResult" in j["components"]["schemas"]
    assert "400" not in op["responses"]  # el dispositivo sale de la key: no hay 400 de dispositivo
    assert "err.main.run_in_progress" in str(op["responses"]["409"])


def test_openapi_fingerprint_operation(client):
    j = client.get("/api/openapi.json").json()
    op = j["paths"]["/api/hook/{game}/fingerprint"]["post"]
    assert op["tags"] == [apidocs.TAG] and op["summary"] and op["security"] == [{"deviceKeyAuth": []}]
    assert {"200", "400", "401", "404", "409", "422", "429"} <= set(op["responses"])
    assert "Validation Error" not in str(op["responses"]["422"])
    assert {p["name"]: p["in"] for p in op["parameters"]} == {
        "game": "path",
        "device": "query",
        "manifest": "query",
    }
    ok = op["responses"]["200"]["content"]["application/json"]
    assert ok["schema"]["$ref"].endswith("/FingerprintResult")
    assert set(ok["examples"]) == {"upload", "download", "download_manifest", "none", "conflict"}
    assert ok["examples"]["download_manifest"]["value"]["hub_manifest"][0]["path"]
    assert "hub_manifest" in j["components"]["schemas"]["FingerprintResult"]["properties"]
    assert "hub_manifest" not in j["components"]["schemas"]["FingerprintResult"].get("required", [])
    assert "hub_manifest" not in ok["examples"]["download"]["value"]
    body = op["requestBody"]["content"]["application/json"]
    assert body["schema"]["type"] == "array" and set(body["schema"]["items"]["properties"]) == {
        "path",
        "sha256",
        "size",
        "mtime",
    }
    assert body["examples"]["manifest"]["value"][0]["path"] and body["examples"]["empty"]["value"] == []
    assert {"FingerprintResult", "FingerprintSide"} <= set(j["components"]["schemas"])
    codes = op["responses"]["422"]["content"]["application/json"]["examples"]
    assert codes["path"]["value"]["detail"]["code"] == "err.hook.manifest_path_invalid"
    assert "409" in op["responses"] and "err.main.run_in_progress" in str(op["responses"]["409"])


FILE_OPS = {
    ("/api/hook/{game}/manifest", "get"): ({"200", "403", "404", "409"}, "HubManifest"),
    ("/api/hook/{game}/files", "get"): ({"200", "206", "400", "403", "404", "409", "416"}, None),
    ("/api/hook/{game}/files", "put"): ({"200", "400", "403", "404", "409", "413", "422"}, "UploadResult"),
    ("/api/hook/{game}/commit", "post"): ({"200", "400", "403", "404", "409", "422"}, "CommitResult"),
}


@pytest.mark.parametrize("key", sorted(FILE_OPS))
def test_openapi_file_operations(client, key):
    path, method = key
    codes, model = FILE_OPS[key]
    op = client.get("/api/openapi.json").json()["paths"][path][method]
    assert op["tags"] == [apidocs.TAG] and op["summary"] and op["description"]
    assert op["security"] == [{"deviceKeyAuth": []}]
    assert (codes | {"401", "429"}) <= set(op["responses"])
    assert {p["name"] for p in op["parameters"]} >= {"game", "device"}
    assert "403" in op["responses"] and "err.apikey.device_mismatch" in str(op["responses"]["403"])
    ok = op["responses"]["200"]["content"]
    if model:
        assert ok["application/json"]["schema"]["$ref"].endswith("/" + model) and ok["application/json"]["examples"]
    for status, r in op["responses"].items():
        if status not in ("200", "206"):
            assert r["description"] and r["content"]["application/json"]["examples"], status


def test_openapi_file_operation_details(client):
    j = client.get("/api/openapi.json").json()
    put = j["paths"]["/api/hook/{game}/files"]["put"]
    assert {p["name"] for p in put["parameters"]} == {"game", "path", "size", "sha256", "offset", "device"}
    assert "application/octet-stream" in put["requestBody"]["content"]
    assert "err.hook.file_too_large" in str(put["responses"]["413"]) and "max_mb" in str(put["responses"]["413"])
    assert "err.hook.upload_offset_mismatch" in str(put["responses"]["409"])
    assert "err.hook.upload_busy" in str(put["responses"]["409"])
    assert "err.hook.staging_full" in str(put["responses"]["413"])
    commit = j["paths"]["/api/hook/{game}/commit"]["post"]
    assert set(commit["requestBody"]["content"]["application/json"]["schema"]["required"]) == {"expect", "manifest"}
    assert "err.hook.upload_incomplete" in str(commit["responses"]["422"])
    get = j["paths"]["/api/hook/{game}/files"]["get"]
    assert {p["name"]: p["in"] for p in get["parameters"]} == {
        "game": "path",
        "path": "query",
        "device": "query",
        "range": "header",
    }
    assert "err.hook.range_invalid" in str(get["responses"]["416"])


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
    """Deriva: una ruta /api/* nueva debe quedar oculta del esquema o ser del tag público (y entonces es una de las rutas de la API key)."""
    public = set()
    for r in apidocs.iter_api_routes(app.routes):
        path = r.path
        if not path.startswith("/api/"):
            continue
        in_public = bool({apidocs.TAG, apidocs.GAMES_TAG} & set(r.tags or []))
        assert in_public or not r.include_in_schema, (
            f"{r.methods} {path}: ni en un tag público ni include_in_schema=False"
        )
        if in_public:
            assert r.include_in_schema and (path.startswith(apidocs.API_PREFIX) or path == apidocs.GAMES_PATH), path
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
