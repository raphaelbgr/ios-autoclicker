"""
Canonical-v1 analytics tracking for the iOS Auto-Clicker.

Emits an append-only JSONL stream (tracks.jsonl) of runtime events with
canonical-v1 timing fields:

    event          dotted event id (e.g. "automation.scan.tick")
    trace_id       groups one logical run (e.g. "automation-a1b2c3")
    ts_local       ISO-8601 local timestamp
    delta_ms       ms since the previous event of ANY id in the same trace
                   (None for the first event of a trace)
    delta_same_ms  ms since the previous event of the SAME id in the same
                   trace (None the first time an id fires in a trace)
    data           free-form JSON payload

The stream is consumed by trace-audit tooling, which replays events by
trace_id and diffs what actually happened against the compile-time
@tracked_flow contracts in tracks/contracts/*.json (exported with
`python -m src.tracking emit-contracts`).

Design rules:
  * Tracking must NEVER break the app — every write is exception-guarded;
    a failing sink disables the stream for the rest of the session.
  * Thread-safe: the automation thread and the GUI thread both emit.
  * Zero heavy imports: safe to import from any module (no Qt, no cv2).

Environment:
  AUTOCLICKER_TRACKS          override the tracks.jsonl path
  AUTOCLICKER_TRACKS_DISABLE  set to "1" to disable emission entirely
"""

import ast
import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.paths import tracks_file

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Runtime output goes to the writable data dir (the sandbox container when
# bundled). CONTRACTS_DIR stays repo-relative — it is authoring/audit tooling
# that reads and writes the source tree, never used inside a shipped bundle.
DEFAULT_TRACKS_PATH = tracks_file()
CONTRACTS_DIR = os.path.join(_REPO_ROOT, "tracks", "contracts")

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "trace_id": None,          # current trace id
    "broken": False,           # sink failed — stop trying
    "last_any": {},            # trace_id -> monotonic ts of last event
    "last_same": {},           # (trace_id, event) -> monotonic ts
}

# Registry of @tracked_flow-decorated functions (runtime introspection)
_FLOWS: Dict[str, Dict[str, Any]] = {}


def tracks_path() -> str:
    """Resolved path of the tracks.jsonl stream."""
    return os.environ.get("AUTOCLICKER_TRACKS", DEFAULT_TRACKS_PATH)


def _enabled() -> bool:
    return os.environ.get("AUTOCLICKER_TRACKS_DISABLE") != "1" and not _state["broken"]


def new_trace(prefix: str = "run") -> str:
    """Start a new trace; subsequent track() calls attach to it."""
    trace_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
    with _lock:
        _state["trace_id"] = trace_id
    return trace_id


def set_trace(trace_id: str) -> None:
    with _lock:
        _state["trace_id"] = trace_id


def current_trace() -> Optional[str]:
    return _state["trace_id"]


def track(event: str, **data: Any) -> Optional[dict]:
    """Emit one canonical-v1 event. Returns the record (or None if disabled).

    Never raises: any failure marks the sink broken and is swallowed.
    """
    if not _enabled():
        return None
    try:
        now_mono = time.monotonic()
        with _lock:
            trace_id = _state["trace_id"]
            if trace_id is None:
                trace_id = f"orphan-{uuid.uuid4().hex[:8]}"
                _state["trace_id"] = trace_id

            last_any = _state["last_any"].get(trace_id)
            last_same = _state["last_same"].get((trace_id, event))
            delta_ms = round((now_mono - last_any) * 1000.0, 3) if last_any is not None else None
            delta_same_ms = round((now_mono - last_same) * 1000.0, 3) if last_same is not None else None
            _state["last_any"][trace_id] = now_mono
            _state["last_same"][(trace_id, event)] = now_mono

        record = {
            "event": event,
            "trace_id": trace_id,
            "ts_local": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "delta_ms": delta_ms,
            "delta_same_ms": delta_same_ms,
            "data": _jsonable(data),
        }

        path = tracks_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return record
    except Exception:
        _state["broken"] = True
        return None


def _jsonable(data: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce payload values to JSON-safe types (never raises)."""
    out = {}
    for k, v in data.items():
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            out[k] = repr(v)
    return out


def tracked_flow(flow: str, events: List[str]) -> Callable:
    """Declare a compile-time flow contract on the function that drives it.

    The decorated function behaves identically; the (flow, events) pair is
    the reference graph the trace audit diffs the runtime stream against.
    Contracts are exported with `python -m src.tracking emit-contracts`,
    which AST-extracts these decorators (no imports required).
    """
    def decorate(fn: Callable) -> Callable:
        _FLOWS[flow] = {
            "flow": flow,
            "function": getattr(fn, "__qualname__", fn.__name__),
            "events": list(events),
        }
        setattr(fn, "__tracked_flow__", _FLOWS[flow])
        return fn
    return decorate


# ──────────────────────────────────────────────────────────────
#  Contract extraction (AST — no runtime imports of the app)
# ──────────────────────────────────────────────────────────────

def extract_contracts(src_dir: Optional[str] = None) -> List[dict]:
    """AST-scan src/ for @tracked_flow("flow", events=[...]) decorators."""
    src_dir = src_dir or os.path.join(_REPO_ROOT, "src")
    contracts = []
    for root, _dirs, files in os.walk(src_dir):
        if "__pycache__" in root:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                tree = ast.parse(open(fpath, encoding="utf-8").read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call):
                        continue
                    fn = dec.func
                    name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                    if name != "tracked_flow":
                        continue
                    flow = None
                    events: List[str] = []
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        flow = dec.args[0].value
                    if len(dec.args) > 1 and isinstance(dec.args[1], (ast.List, ast.Tuple)):
                        events = [e.value for e in dec.args[1].elts
                                  if isinstance(e, ast.Constant)]
                    for kw in dec.keywords:
                        if kw.arg == "events" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            events = [e.value for e in kw.value.elts
                                      if isinstance(e, ast.Constant)]
                    if flow:
                        contracts.append({
                            "flow": flow,
                            "function": node.name,
                            "events": events,
                            "extracted_from": os.path.relpath(fpath, _REPO_ROOT),
                        })
    return contracts


def emit_contracts(out_dir: Optional[str] = None) -> List[str]:
    """Write one JSON contract file per @tracked_flow found in src/."""
    out_dir = out_dir or CONTRACTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for c in extract_contracts():
        path = os.path.join(out_dir, c["flow"].replace(".", "_") + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=2)
        written.append(path)
    return written


def _reset_for_tests() -> None:
    """Test hook: clear trace/delta state (does not touch the file)."""
    with _lock:
        _state["trace_id"] = None
        _state["broken"] = False
        _state["last_any"].clear()
        _state["last_same"].clear()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "emit-contracts":
        paths = emit_contracts()
        for p in paths:
            print(f"wrote {p}")
        print(f"{len(paths)} contract(s)")
    else:
        print("usage: python -m src.tracking emit-contracts")
