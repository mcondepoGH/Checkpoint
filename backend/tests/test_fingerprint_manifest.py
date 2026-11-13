"""fingerprint_from_manifest: misma huella que fingerprint() de un directorio, a partir de un manifiesto."""

import hashlib
import os
import random

import pytest

from app.sync.fingerprint import ManifestError, fingerprint, fingerprint_from_manifest


def put(root, rel, content, mtime):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(content)
    os.utime(f, (mtime, mtime))


def manifest_of(root):
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out.append(
                {
                    "path": p.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                }
            )
    return out


def test_equivale_al_hash_real_del_directorio(tmp_path):
    put(tmp_path, "a.sav", b"uno", 1000)
    put(tmp_path, "sub/b.sav", b"dos dos", 2000)
    put(tmp_path, "sub/deep/c.dat", b"", 1500)
    real = fingerprint(tmp_path)
    m = manifest_of(tmp_path)
    random.Random(1).shuffle(m)  # el orden del manifiesto no importa
    got = fingerprint_from_manifest(m)
    assert got == real
    assert (got.files, got.size, got.mtime) == (3, 3 + 7 + 0, 2000)


def test_vacio_como_directorio_vacio(tmp_path):
    assert fingerprint_from_manifest([]) == fingerprint(tmp_path)
    assert fingerprint_from_manifest([]).empty


def test_normaliza_rutas():
    base = {"sha256": "a" * 64, "size": 1, "mtime": 5}
    a = fingerprint_from_manifest([{**base, "path": "x\\y/./z.sav"}])
    b = fingerprint_from_manifest([{**base, "path": "x/y/z.sav"}])
    assert a == b


def test_sha_en_mayusculas_equivale():
    e = {"path": "a", "size": 1, "mtime": 1}
    assert fingerprint_from_manifest([{**e, "sha256": "AB" * 32}]) == fingerprint_from_manifest(
        [{**e, "sha256": "ab" * 32}]
    )


@pytest.mark.parametrize("path", ["../x", "a/../b", "/abs", "\\abs", "", ".", "a/", "a\0b", "a/..", "//x"])
def test_rechaza_rutas_peligrosas(path):
    with pytest.raises(ManifestError) as e:
        fingerprint_from_manifest([{"path": path, "sha256": "a" * 64, "size": 1, "mtime": 1}])
    assert e.value.code == "err.hook.manifest_path_invalid"


@pytest.mark.parametrize(
    "path", ["it's.sav", "a&b.sav", "slot:1/x.sav", "Mi Partida/s 1.sav", "a;b", "C:/x", "é$%.sav"]
)
def test_acepta_nombres_como_fingerprint_real(tmp_path, path):
    """Un save con `'`, `&`, `:` o espacios debe poder igualar al hub: no se filtra por `PATH_CHARS_RE`."""
    put(tmp_path, path, b"x", 10)
    assert fingerprint_from_manifest(manifest_of(tmp_path)) == fingerprint(tmp_path)


def test_rechaza_duplicados_tras_normalizar():
    e = {"sha256": "a" * 64, "size": 1, "mtime": 1}
    with pytest.raises(ManifestError) as x:
        fingerprint_from_manifest([{**e, "path": "a/b"}, {**e, "path": "a\\b"}])
    assert x.value.code == "err.hook.manifest_duplicate"


@pytest.mark.parametrize("sha", ["", "xyz", "a" * 63, "g" * 64])
def test_rechaza_sha_invalido(sha):
    with pytest.raises(ManifestError) as e:
        fingerprint_from_manifest([{"path": "a", "sha256": sha, "size": 1, "mtime": 1}])
    assert e.value.code == "err.hook.manifest_sha_invalid"


def test_orden_por_componentes_como_rglob(tmp_path):
    """`a.sav` va después de `a/b.sav` en sorted(rglob) aunque como texto '.' < '/'."""
    put(tmp_path, "a.sav", b"1", 10)
    put(tmp_path, "a/b.sav", b"2", 20)
    put(tmp_path, "a-x", b"3", 30)
    assert fingerprint_from_manifest(manifest_of(tmp_path)) == fingerprint(tmp_path)
