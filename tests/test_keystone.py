"""The keystone contract test for the k8s-exercise service.

One test, over a real socket, against the running container. If this fails, the
other 90 tests in this suite have been measuring a service that does not work:
they all run in-process, so none of them can see a wrong port, an unregistered
route, a serialization mismatch, or an image that builds but never starts.

Deliberately over the wire rather than through `fastapi.testclient.TestClient`.
TestClient speaks ASGI in-process -- no socket, no port, no uvicorn startup --
so it is blind to precisely the failures that justify this test's existence. It
would also drag `app.py` into pytest's import graph during normal test runs,
whereas HTTP keeps that boundary intact.

Run it:

    docker compose up -d --build
    uv run pytest -m keystone
    docker compose down

With nothing listening it skips (visibly, with a reason) rather than failing --
absence of the precondition is not evidence of a broken service. What it must
never do is vanish silently from a run; see the `markers` note in pyproject.toml.
"""

from __future__ import annotations

import os

import httpx2
import pytest

# docker-compose.yml publishes 8000:8000 and app.py sets root_path="/api/v1"
BASE_URL = os.environ.get("KEYSTONE_BASE_URL", "http://127.0.0.1:8000/api/v1")
TIMEOUT = 5.0

# Layers interleave entities and statements because E ⊆ V: a statement is a full
# member of V, so the walk traverses *through* alice-works_for-acme rather than
# around it. Asserting the literal shape is the point -- this is the claim the
# rest of the suite cannot make. Sets converted to sorted lists for comparison.
EXPECTED_BFS = [
    {"alice"},
    {"acme", "alice-works_for-acme"},
    {"acme-owns-car1", "car1"},
]


def _service_up(base_url: str) -> bool:
    try:
        return httpx2.get(f"{base_url}/healthz", timeout=TIMEOUT).status_code == 200
    except httpx2.RequestError:
        return False


@pytest.mark.keystone
def test_service_contract_over_the_wire() -> None:
    """Seed domain reachable end to end: health, entity, edges, BFS, 404."""
    if not _service_up(BASE_URL):
        pytest.skip(
            f"no service listening at {BASE_URL} -- start it with: "
            "docker compose up -d --build"
        )

    with httpx2.Client(base_url=BASE_URL, timeout=TIMEOUT) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        entity = client.get("/entities/alice")
        assert entity.status_code == 200
        assert entity.json()["id"] == "alice"

        edges = client.get("/entities/alice/edges", params={"direction": "out"})
        assert edges.status_code == 200
        assert [(e["id"], e["type"]) for e in edges.json()] == [
            ("alice-works_for-acme", "WorksFor")
        ]

        walk = client.get("/bfs", params={"seed": "alice", "max_hops": 2})
        assert walk.status_code == 200
        # Convert lists to sets for order-independent comparison
        assert [set(layer) for layer in walk.json()] == EXPECTED_BFS

        # an unknown id is a clean 404, not a 500
        missing = client.get("/entities/nobody")
        assert missing.status_code == 404
