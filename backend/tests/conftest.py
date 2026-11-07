import pytest


@pytest.fixture(autouse=True)
def _runtime_native_por_defecto(monkeypatch):
    """Los tests no dependen de si la máquina es un contenedor (/.dockerenv): por defecto, modo nativo.
    Los que prueban Docker lo fijan con monkeypatch.setenv("CHECKPOINT_RUNTIME", "docker")."""
    monkeypatch.setenv("CHECKPOINT_RUNTIME", "native")
