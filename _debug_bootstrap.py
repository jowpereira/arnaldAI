"""Debug script for bootstrap context test."""

from pathlib import Path
import tempfile
from arnaldo.kernel import ArnaldoKernel
from arnaldo.runtime import GraphRuntime, SandboxManager
from arnaldo.memory import MemoryStore
from arnaldo.session import SessionManager
from arnaldo.capabilities.catalog import CapabilityCatalog
from arnaldo.components import ToolForge
from arnaldo.proactivity import ProactivityManager
from arnaldo.graph import CognitiveGraph, EdgeKind, NodeKind, MemoryNode

from tests.test_graph_runtime_integration import AlwaysSuccessClient, CaptureMessagesClient

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    rt1 = GraphRuntime(llm_client=AlwaysSuccessClient())
    k1 = ArnaldoKernel(
        runtime=rt1,
        memory=MemoryStore(base / "memory"),
        session_manager=SessionManager(base / "sessions"),
        tool_forge=ToolForge(base / "tool_forge"),
        capabilities=CapabilityCatalog(registry_path=base / "cap.json"),
        sandbox_manager=SandboxManager(base / "sb"),
        proactivity=ProactivityManager(base / "proact"),
    )
    k1.intent_compiler._llm_client = rt1.llm_client
    r1 = k1.run(
        "Planeje execucao inicial com alternativas e revisao",
        output_dir=base / "runs",
        session_id="sess1",
    )
    g1 = CognitiveGraph.load(r1.files["execution_graph"])
    print("=== Run 1 Graph ===")
    print(f"Nodes: {g1.node_count}, Edges: {g1.edge_count}")
    for n in g1.iter_nodes(kind=NodeKind.SYNAPSE):
        mentions = list(g1.iter_edges_from(n.id, kinds=[EdgeKind.MENTIONS]))
        print(f"  SYN {n.id} -> MENTIONS={len(mentions)}")
    for n in g1.iter_nodes(kind=NodeKind.MEMORY):
        p = n.payload if isinstance(n.payload, dict) else {}
        has_result = isinstance(p.get("result"), dict)
        print(f"  MEM {n.id} is_MemoryNode={isinstance(n, MemoryNode)} has_result={has_result}")

    # Second run
    cc = CaptureMessagesClient()
    rt2 = GraphRuntime(llm_client=cc)
    k2 = ArnaldoKernel(
        runtime=rt2,
        memory=MemoryStore(base / "memory"),
        session_manager=SessionManager(base / "sessions"),
        tool_forge=ToolForge(base / "tool_forge"),
        capabilities=CapabilityCatalog(registry_path=base / "cap.json"),
        sandbox_manager=SandboxManager(base / "sb"),
        proactivity=ProactivityManager(base / "proact"),
    )
    k2.intent_compiler._llm_client = cc
    r2 = k2.run(
        "Continue e refine o plano com base no historico",
        output_dir=base / "runs",
        session_id=r1.session_id,
    )
    print("\n=== Run 2 ===")
    print(f"Messages captured: {len(cc.user_messages)}")
    for i, msg in enumerate(cc.user_messages):
        has_context = "Contexto" in msg
        print(f"  msg[{i}]: has_context={has_context} len={len(msg)} first_100={msg[:100]}")
