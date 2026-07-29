"""Tests for the Graph container (graph.py)."""

from __future__ import annotations

import pytest

from base import TruthStatus
from graph import Graph
from example import (
    Knows,
    Organization,
    Person,
    WorksFor,
    acme,
    alice,
    bob,
)


def _wf(truth_status: TruthStatus = "asserted_true") -> WorksFor:
    return WorksFor(id="wf1", subject=alice, object_=acme, truth_status=truth_status)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_empty_constructor_creates_empty_graph() -> None:
    g = Graph()
    assert g.by_id == {}


def test_entity_indexed_by_id() -> None:
    g = Graph([alice])
    assert g.get("alice") is alice


def test_statement_indexed_in_by_id_and_edges() -> None:
    wf = _wf()
    g = Graph([alice, acme, wf])
    assert g.get("wf1") is wf
    assert wf in g.out_edges["alice"]
    assert wf in g.in_edges["acme"]


def test_add_accepts_entities_and_statements() -> None:
    wf = _wf()
    g = Graph()
    g.add(alice)
    g.add(acme)
    g.add(wf)
    assert g.get("alice") is alice
    assert g.get("acme") is acme
    assert g.get("wf1") is wf
    assert g.edges_from("alice") == [wf]


def test_extend_matches_bulk_constructor_behavior() -> None:
    wf = _wf()
    g = Graph()
    g.extend([alice, acme, wf])
    assert g.get("alice") is alice
    assert g.get("wf1") is wf
    assert g.edges_to("acme") == [wf]


def test_non_instance_objects_skipped() -> None:
    """Callables and non-id objects must not crash or pollute the index."""
    g = Graph([alice, lambda x: x, 42, "string"])
    assert list(g.by_id.keys()) == ["alice"]


def test_id_collision_warns() -> None:
    alice2 = Person(id="alice", name="Alice-dupe")
    with pytest.warns(UserWarning, match="collision") as record:
        g = Graph([alice, alice2])
    assert len(record) == 1
    assert g.get("alice") is alice2  # last write wins


# ---------------------------------------------------------------------------
# from_module
# ---------------------------------------------------------------------------


def test_from_module_collects_instances() -> None:
    import example

    g = Graph.from_module(example)
    assert g.get("alice") is alice
    assert g.get("acme") is acme


# ---------------------------------------------------------------------------
# edges_from / edges_to
# ---------------------------------------------------------------------------


def test_edges_from_unfiltered() -> None:
    wf = _wf()
    g = Graph([alice, acme, wf])
    assert g.edges_from("alice") == [wf]


def test_edges_from_pred_type_filter() -> None:
    wf = _wf()
    k = Knows(id="k1", subject=alice, object_=bob, truth_status="asserted_true")
    g = Graph([alice, acme, bob, wf, k])
    assert g.edges_from("alice", pred_type=WorksFor) == [wf]
    assert g.edges_from("alice", pred_type=Knows) == [k]


def test_edges_from_truth_filter_excludes_non_asserted() -> None:
    wf_true = _wf("asserted_true")
    wf_hyp = WorksFor(
        id="wf2", subject=alice, object_=acme, truth_status="hypothetical"
    )
    g = Graph([alice, acme, wf_true, wf_hyp])
    result = g.edges_from("alice", truth="asserted_true")
    assert wf_true in result
    assert wf_hyp not in result


def test_edges_from_truth_set() -> None:
    wf_true = _wf("asserted_true")
    wf_false = WorksFor(
        id="wf2", subject=alice, object_=acme, truth_status="asserted_false"
    )
    g = Graph([alice, acme, wf_true, wf_false])
    result = g.edges_from("alice", truth={"asserted_true", "asserted_false"})
    assert wf_true in result
    assert wf_false in result


def test_edges_to_unfiltered() -> None:
    wf = _wf()
    g = Graph([alice, acme, wf])
    assert g.edges_to("acme") == [wf]


def test_edges_to_truth_filter() -> None:
    wf = _wf("hypothetical")
    g = Graph([alice, acme, wf])
    assert g.edges_to("acme", truth="asserted_true") == []
    assert g.edges_to("acme", truth="hypothetical") == [wf]


def test_get_returns_none_for_unknown() -> None:
    g = Graph([alice])
    assert g.get("nobody") is None


# ---------------------------------------------------------------------------
# BFS
# ---------------------------------------------------------------------------


def test_bfs_seed_in_layer_zero() -> None:
    g = Graph([alice])
    layers = g.bfs(["alice"])
    assert "alice" in layers[0]


def test_bfs_reaches_neighbor_at_hop_one() -> None:
    wf = _wf()
    g = Graph([alice, acme, wf])
    layers = g.bfs(["alice"], max_hops=1)
    assert "acme" in layers[1]


def test_bfs_does_not_revisit_nodes() -> None:
    k = Knows(id="k1", subject=alice, object_=bob, truth_status="asserted_true")
    g = Graph([alice, bob, k])
    layers = g.bfs(["alice", "bob"], max_hops=2)
    all_ids = [eid for layer in layers for eid in layer]
    assert len(all_ids) == len(set(all_ids))


def test_bfs_respects_truth_filter() -> None:
    wf_hyp = WorksFor(
        id="wf-hyp", subject=alice, object_=acme, truth_status="hypothetical"
    )
    g = Graph([alice, acme, wf_hyp])
    layers = g.bfs(["alice"], max_hops=2, truth_values=("asserted_true",))
    all_found = {eid for layer in layers for eid in layer}
    assert "acme" not in all_found


def test_bfs_traverses_inward_edges() -> None:
    wf = _wf()
    g = Graph([alice, acme, wf])
    layers = g.bfs(["acme"], max_hops=1)
    assert "alice" in layers[1]


# ---------------------------------------------------------------------------
# transitive_closure
# ---------------------------------------------------------------------------


def test_transitive_closure_direct_chain() -> None:
    from base import BaseStatement

    class PartOf(BaseStatement[Organization, Organization]):
        pass

    dept = Organization(id="dept", name="Dept", industry="x")
    div = Organization(id="div", name="Div", industry="x")
    co = Organization(id="co", name="Co", industry="x")
    e1 = PartOf(id="e1", subject=dept, object_=div, truth_status="asserted_true")
    e2 = PartOf(id="e2", subject=div, object_=co, truth_status="asserted_true")
    g = Graph([dept, div, co, e1, e2])
    reachable = g.transitive_closure("dept", PartOf)
    assert "div" in reachable
    assert "co" in reachable


def test_transitive_closure_empty_when_no_edges() -> None:
    g = Graph([alice])
    assert g.transitive_closure("alice", WorksFor) == set()


# ---------------------------------------------------------------------------
# describe / print_edges
# ---------------------------------------------------------------------------


def test_describe_unknown_id() -> None:
    g = Graph([alice])
    assert "not found" in g.describe("nobody")


def test_describe_known_id() -> None:
    g = Graph([alice])
    result = g.describe("alice")
    assert isinstance(result, str)
    assert len(result) > 0


def test_print_edges_runs_without_error(capsys: pytest.CaptureFixture[str]) -> None:
    wf = _wf()
    g = Graph([alice, acme, wf])
    g.print_edges(g.edges_from("alice"))
    out = capsys.readouterr().out
    assert "asserted_true" in out
