"""Tests for src/tracking.py — canonical-v1 stream + contract extraction."""

import json
import os

import pytest

import src.tracking as tracking


@pytest.fixture()
def stream(tmp_path, monkeypatch):
    """Isolated tracks.jsonl per test."""
    path = tmp_path / "tracks.jsonl"
    monkeypatch.setenv("AUTOCLICKER_TRACKS", str(path))
    tracking._reset_for_tests()
    yield path
    tracking._reset_for_tests()


def read_events(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


class TestTrack:
    def test_canonical_v1_fields(self, stream):
        tracking.new_trace("t")
        rec = tracking.track("unit.first", foo=1, bar="x")
        assert rec is not None
        events = read_events(stream)
        assert len(events) == 1
        e = events[0]
        assert e["event"] == "unit.first"
        assert e["trace_id"].startswith("t-")
        assert e["delta_ms"] is None          # first event of the trace
        assert e["delta_same_ms"] is None
        assert e["data"] == {"foo": 1, "bar": "x"}
        assert "ts_local" in e

    def test_delta_ms_and_delta_same_ms(self, stream):
        import time
        tracking.new_trace("t")
        tracking.track("a")
        time.sleep(0.02)
        tracking.track("b")
        time.sleep(0.02)
        tracking.track("a")
        a1, b, a2 = read_events(stream)
        assert b["delta_ms"] >= 15            # since previous ANY event
        assert b["delta_same_ms"] is None     # first "b"
        assert a2["delta_ms"] >= 15
        assert a2["delta_same_ms"] >= 35      # since previous "a"

    def test_new_trace_resets_deltas(self, stream):
        tracking.new_trace("one")
        tracking.track("x")
        tracking.new_trace("two")
        rec = tracking.track("x")
        assert rec["delta_ms"] is None        # fresh trace
        assert rec["delta_same_ms"] is None
        assert rec["trace_id"].startswith("two-")

    def test_orphan_events_get_a_trace(self, stream):
        rec = tracking.track("loose")
        assert rec["trace_id"].startswith("orphan-")

    def test_disabled_via_env(self, stream, monkeypatch):
        monkeypatch.setenv("AUTOCLICKER_TRACKS_DISABLE", "1")
        assert tracking.track("nope") is None
        assert not stream.exists()

    def test_unserializable_payload_is_reprd(self, stream):
        tracking.new_trace("t")
        rec = tracking.track("weird", obj=object())
        assert "object object" in rec["data"]["obj"]

    def test_never_raises_on_bad_sink(self, tmp_path, monkeypatch):
        # Point the stream at an unwritable location: track() must not raise
        monkeypatch.setenv("AUTOCLICKER_TRACKS", "/dev/null/impossible/tracks.jsonl")
        tracking._reset_for_tests()
        assert tracking.track("x") is None
        assert tracking._state["broken"] is True
        tracking._reset_for_tests()


class TestContracts:
    def test_extract_finds_declared_flows(self):
        contracts = {c["flow"]: c for c in tracking.extract_contracts()}
        assert "app.startup" in contracts
        assert "automation.run" in contracts
        auto = contracts["automation.run"]
        assert auto["function"] == "_automation_loop"
        assert "automation.scan.tick" in auto["events"]
        assert auto["events"].index("automation.match.found") > \
               auto["events"].index("automation.refs.loaded")

    def test_emit_contracts_writes_files(self, tmp_path):
        written = tracking.emit_contracts(str(tmp_path))
        assert len(written) >= 2
        for p in written:
            c = json.load(open(p))
            assert {"flow", "function", "events", "extracted_from"} <= set(c)

    def test_tracked_flow_decorator_registers_and_preserves_fn(self):
        @tracking.tracked_flow("test.flow", events=["a", "b"])
        def sample(x):
            return x * 2

        assert sample(21) == 42
        assert sample.__tracked_flow__["flow"] == "test.flow"
        assert tracking._FLOWS["test.flow"]["events"] == ["a", "b"]
