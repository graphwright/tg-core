"""Minimal FastAPI service exposing the typed graph for testing.

Provides REST endpoints for entity lookup, edge traversal, and BFS walks over
the example domain (alice, acme, car1). Exists to validate the keystone test's
contract: if this service is reachable over HTTP and returns the expected shapes,
the core graph implementation works end-to-end.

Run with:
    docker compose up -d --build
    curl http://localhost:8000/api/v1/healthz
"""

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from base import Provenance
from example import Owns, WorksFor, acme, alice, car
from graph import Graph

app = FastAPI(
    title="Typed Graph API",
    description="Minimal service for keystone contract testing",
    version="0.1.0",
    root_path="/api/v1",
)

# Build the graph from the example domain
graph = Graph()
graph.add(alice)
graph.add(acme)
graph.add(car)

# Add relationships
prov = Provenance(source="api.example.com", extraction_method="manual")
works_for = WorksFor(
    id="alice-works_for-acme",
    subject=alice,
    object_=acme,
    truth_status="asserted_true",
    provenance=(prov,),
)
graph.add(works_for)

owns = Owns(
    id="acme-owns-car1",
    subject=acme,
    object_=car,
    truth_status="asserted_true",
    provenance=(prov,),
)
graph.add(owns)


class HealthResponse(BaseModel):
    status: Literal["ok"]


class EntityResponse(BaseModel):
    id: str
    type: str


class EdgeResponse(BaseModel):
    id: str
    type: str
    subject_id: str
    object_id: str


@app.get("/healthz", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok")


@app.get("/entities/{entity_id}", response_model=EntityResponse)
def get_entity(entity_id: str) -> EntityResponse:
    """Retrieve a single entity by ID."""
    instance = graph.get(entity_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

    return EntityResponse(
        id=instance.id,
        type=type(instance).__name__,
    )


@app.get("/entities/{entity_id}/edges", response_model=list[EdgeResponse])
def get_edges(
    entity_id: str,
    direction: Literal["in", "out"] = Query(..., description="Edge direction"),
) -> list[EdgeResponse]:
    """Get edges connected to an entity."""
    instance = graph.get(entity_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")

    if direction == "out":
        edges = graph.edges_from(entity_id)
    else:
        edges = graph.edges_to(entity_id)

    return [
        EdgeResponse(
            id=edge.id,
            type=type(edge).__name__,
            subject_id=edge.subject.id,
            object_id=edge.object_.id,
        )
        for edge in edges
    ]


@app.get("/bfs", response_model=list[list[str]])
def bfs(
    seed: str = Query(..., description="Starting entity ID"),
    max_hops: int = Query(3, ge=1, le=10, description="Maximum hops"),
) -> list[list[str]]:
    """Breadth-first traversal from a seed entity.

    Returns layers of instance IDs, where each layer contains all instances
    reachable in exactly N hops from the seed. Edges are instances too (E ⊆ V),
    so layers interleave entities and statements.
    """
    instance = graph.get(seed)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Seed {seed} not found")

    layers = graph.bfs([seed], max_hops=max_hops)
    return [list(layer) for layer in layers]
