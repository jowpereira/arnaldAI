from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile

from arnaldo.graph import CognitiveGraph, EdgeKind, ExecutionEngine, GraphEdge, StepContext, SynapseNode
from arnaldo.llm.structured import TypedResponse


@dataclass
class SynapseOutput:
    result: str
    evidence: list[str]


class FakeTypedClient:
    is_configured = True

    def __init__(
        self,
        *,
        responses: list[TypedResponse[SynapseOutput]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, object]] = []

    def chat_typed(self, tier: str, messages: list[dict[str, str]], **kwargs: object) -> TypedResponse[SynapseOutput]:
        self.calls.append({"tier": tier, "messages": messages, "kwargs": kwargs})
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("fake sem resposta")
        return self.responses.pop(0)


def _typed_success() -> TypedResponse[SynapseOutput]:
    return TypedResponse(
        parsed=SynapseOutput(result="ok", evidence=["e1"]),
        refusal=None,
        raw={},
        schema_used={},
        retries=0,
    )


def _typed_refusal(reason: str = "blocked") -> TypedResponse[SynapseOutput]:
    return TypedResponse(
        parsed=None,
        refusal=reason,
        raw={},
        schema_used={},
        retries=0,
    )


def _build_graph_with_synapse() -> tuple[CognitiveGraph, SynapseNode]:
    graph = CognitiveGraph()
    synapse = SynapseNode.specialist(
        "Critic",
        role="critic",
        objective="avaliar riscos",
        output_contract_model=SynapseOutput,
    )
    graph.add_node(synapse)
    return graph, synapse


def test_execute_synapse_success_updates_context_and_plasticity() -> None:
    graph, synapse = _build_graph_with_synapse()
    client = FakeTypedClient(responses=[_typed_success()])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
    )

    ctx = StepContext()
    result = engine.execute_synapse(synapse.id, request="analise este plano", context=ctx)

    assert result.success is True
    assert result.fallback_used is False
    assert synapse.id in ctx.outputs
    assert isinstance(ctx.outputs[synapse.id], SynapseOutput)
    updated = graph.get_node(synapse.id)
    assert updated is not None
    assert updated.stats.successes == 1
    assert updated.weight > 0.5
    assert len(client.calls) == 1


def test_execute_synapse_applies_step_level_llm_hints() -> None:
    graph, synapse = _build_graph_with_synapse()
    tuned = synapse.with_payload_merge(
        max_tokens=321,
        timeout=7.5,
        temperature=0.15,
        max_retries=1,
        reasoning_effort="low",
    )
    graph.add_node(tuned)
    client = FakeTypedClient(responses=[_typed_success()])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
    )

    result = engine.execute_synapse(tuned.id, request="analise este plano", context=StepContext(), max_retries=2)

    assert result.success is True
    kwargs = client.calls[0]["kwargs"]
    assert kwargs["max_tokens"] == 321
    assert kwargs["timeout"] == 7.5
    assert kwargs["temperature"] == 0.15
    assert kwargs["max_retries"] == 1
    assert kwargs["reasoning_effort"] == "low"


def test_execute_synapse_applies_runtime_defaults_for_timeout_tokens_and_effort() -> None:
    graph, synapse = _build_graph_with_synapse()
    client = FakeTypedClient(responses=[_typed_success()])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
    )

    result = engine.execute_synapse(synapse.id, request="analise este plano", context=StepContext())

    assert result.success is True
    kwargs = client.calls[0]["kwargs"]
    assert kwargs["timeout"] == 240.0
    assert kwargs["max_tokens"] == 1400
    assert kwargs["reasoning_effort"] == "medium"


def test_execute_synapse_emits_prompt_prepared_callback() -> None:
    graph, synapse = _build_graph_with_synapse()
    client = FakeTypedClient(responses=[_typed_success()])
    captured: list[dict[str, object]] = []
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
        on_prompt_prepared=lambda payload: captured.append(payload),
    )

    result = engine.execute_synapse(synapse.id, request="analise este plano", context=StepContext())

    assert result.success is True
    assert len(captured) == 1
    event = captured[0]
    assert event["node_id"] == synapse.id
    assert event["tier"] == "expert"
    assert event["response_model"] == "SynapseOutput"
    assert isinstance(event["messages"], list)
    assert isinstance(event["chat_kwargs"], dict)


def test_execute_synapse_refusal_raises_in_strict_mode() -> None:
    graph, synapse = _build_graph_with_synapse()
    client = FakeTypedClient(responses=[_typed_refusal("safety")])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
    )
    ctx = StepContext()

    try:
        engine.execute_synapse(synapse.id, request="acao proibida", context=ctx)
        assert False, "esperava RuntimeError em strict mode"
    except RuntimeError as exc:
        assert "refusal" in str(exc)
    assert len(ctx.refusals) == 1
    updated = graph.get_node(synapse.id)
    assert updated is not None
    assert updated.stats.failures == 1
    assert updated.weight < 0.5


def test_execute_synapse_fallback_when_model_missing() -> None:
    graph, synapse = _build_graph_with_synapse()
    client = FakeTypedClient(responses=[_typed_success()])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={},  # sem registro do SynapseOutput
        strict_real=False,
    )
    ctx = StepContext()

    result = engine.execute_synapse(synapse.id, request="analise", context=ctx)

    assert result.success is True
    assert result.fallback_used is True
    assert result.output["reason"] == "missing_output_contract_model"
    updated = graph.get_node(synapse.id)
    assert updated is not None
    # fallback não reforça nem penaliza peso
    assert updated.stats.successes == 0
    assert updated.stats.failures == 0
    assert updated.stats.activations == 1
    assert len(client.calls) == 0


def test_execute_synapse_records_error_when_llm_raises() -> None:
    graph, synapse = _build_graph_with_synapse()
    client = FakeTypedClient(error=RuntimeError("network down"))
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
        strict_real=False,
    )
    ctx = StepContext()

    result = engine.execute_synapse(synapse.id, request="analise", context=ctx)

    assert result.success is False
    assert "network down" in (result.error or "")
    assert len(ctx.errors) == 1
    updated = graph.get_node(synapse.id)
    assert updated is not None
    assert updated.stats.failures == 1


def test_step_context_tracks_versioned_related_history() -> None:
    ctx = StepContext()
    ctx.write("syn_a", {"status": "planned"}, action="frame_intent", agent_id="framer", channel="llm")
    ctx.write(
        "syn_tool",
        {"status": "executed", "result": {"ok": True}},
        action="execute_tooling",
        agent_id="toolrunner_connector_runtime",
        capability_id="connector.runtime",
        channel="tool",
    )
    ctx.write("syn_c", {"status": "reviewed"}, action="critic_review", agent_id="critic", channel="llm")

    related = ctx.snapshot_related_outputs(
        action="stabilize_tooling",
        capability_id="connector.runtime",
        limit=3,
    )

    assert ctx.version == 3
    assert len(related) == 1
    assert related[0]["capability_id"] == "connector.runtime"
    assert related[0]["channel"] == "tool"
    assert related[0]["status"] == "executed"


def test_register_contract_model_rejects_collision() -> None:
    graph, _ = _build_graph_with_synapse()
    engine = ExecutionEngine(graph=graph)
    engine.register_contract_model(SynapseOutput, name="SynapseOutput")

    @dataclass
    class Another:
        result: str

    try:
        engine.register_contract_model(Another, name="SynapseOutput")
        assert False, "esperava ValueError por colisão de nome"
    except ValueError:
        pass


def test_plan_activates_path_uses_highest_weight_and_stops_on_cycle() -> None:
    graph = CognitiveGraph()
    a = SynapseNode.specialist("A", role="a", objective="oa")
    b = SynapseNode.specialist("B", role="b", objective="ob")
    c = SynapseNode.specialist("C", role="c", objective="oc")
    graph.add_node(a)
    graph.add_node(b)
    graph.add_node(c)

    graph.add_edge(GraphEdge.connect(a.id, b.id, EdgeKind.ACTIVATES, weight=0.2))
    graph.add_edge(GraphEdge.connect(a.id, c.id, EdgeKind.ACTIVATES, weight=0.9))
    graph.add_edge(GraphEdge.connect(c.id, a.id, EdgeKind.ACTIVATES, weight=0.8))  # ciclo

    engine = ExecutionEngine(graph=graph)
    path = engine.plan_activates_path(a.id, max_steps=5)

    assert path == [a.id, c.id]


def test_execute_activates_chain_runs_planned_path() -> None:
    graph = CognitiveGraph()
    first = SynapseNode.specialist(
        "First",
        role="framer",
        objective="o1",
        output_contract_model=SynapseOutput,
    )
    second = SynapseNode.specialist(
        "Second",
        role="critic",
        objective="o2",
        output_contract_model=SynapseOutput,
    )
    graph.add_node(first)
    graph.add_node(second)
    graph.add_edge(GraphEdge.connect(first.id, second.id, EdgeKind.ACTIVATES, weight=0.7))

    client = FakeTypedClient(responses=[_typed_success(), _typed_success()])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
        strict_real=False,
    )
    path, ctx, results = engine.execute_activates_chain(first.id, request="execute cadeia")

    assert path == [first.id, second.id]
    assert len(results) == 2
    assert all(r.success for r in results)
    assert first.id in ctx.outputs
    assert second.id in ctx.outputs
    assert len(client.calls) == 2


def test_execute_activates_chain_updates_activates_edge_after_success() -> None:
    graph = CognitiveGraph()
    first = SynapseNode.specialist(
        "First",
        role="framer",
        objective="o1",
        output_contract_model=SynapseOutput,
    )
    second = SynapseNode.specialist(
        "Second",
        role="critic",
        objective="o2",
        output_contract_model=SynapseOutput,
    )
    graph.add_node(first)
    graph.add_node(second)
    edge = GraphEdge.connect(first.id, second.id, EdgeKind.ACTIVATES, weight=0.30)
    graph.add_edge(edge)

    client = FakeTypedClient(responses=[_typed_success(), _typed_success()])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
        strict_real=False,
    )
    engine.execute_activates_chain(first.id, request="execute cadeia com reforco")

    updated_edge = graph.get_edge(edge.id)
    assert updated_edge is not None
    assert updated_edge.successes == 1
    assert updated_edge.failures == 0
    assert updated_edge.weight > 0.30


def test_execute_activates_chain_penalizes_activates_edge_on_failure() -> None:
    graph = CognitiveGraph()
    first = SynapseNode.specialist(
        "First",
        role="framer",
        objective="o1",
        output_contract_model=SynapseOutput,
    )
    second = SynapseNode.specialist(
        "Second",
        role="critic",
        objective="o2",
        output_contract_model=SynapseOutput,
    )
    graph.add_node(first)
    graph.add_node(second)
    edge = GraphEdge.connect(first.id, second.id, EdgeKind.ACTIVATES, weight=0.60)
    graph.add_edge(edge)

    client = FakeTypedClient(responses=[_typed_success(), _typed_refusal("blocked")])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
        strict_real=False,
    )
    engine.execute_activates_chain(first.id, request="execute cadeia com falha")

    updated_edge = graph.get_edge(edge.id)
    assert updated_edge is not None
    assert updated_edge.successes == 0
    assert updated_edge.failures == 1
    assert updated_edge.weight < 0.60


def test_plan_and_execute_activates_reachable_covers_branches() -> None:
    graph = CognitiveGraph()
    root = SynapseNode.specialist(
        "Root",
        role="framer",
        objective="root",
        output_contract_model=SynapseOutput,
    )
    left = SynapseNode.specialist(
        "Left",
        role="explorer",
        objective="left",
        output_contract_model=SynapseOutput,
    )
    right = SynapseNode.specialist(
        "Right",
        role="explorer",
        objective="right",
        output_contract_model=SynapseOutput,
    )
    sink = SynapseNode.specialist(
        "Sink",
        role="critic",
        objective="sink",
        output_contract_model=SynapseOutput,
    )
    for node in (root, left, right, sink):
        graph.add_node(node)
    graph.add_edge(GraphEdge.connect(root.id, left.id, EdgeKind.ACTIVATES, weight=0.9))
    graph.add_edge(GraphEdge.connect(root.id, right.id, EdgeKind.ACTIVATES, weight=0.85))
    graph.add_edge(GraphEdge.connect(left.id, sink.id, EdgeKind.ACTIVATES, weight=0.8))
    graph.add_edge(GraphEdge.connect(right.id, sink.id, EdgeKind.ACTIVATES, weight=0.75))

    client = FakeTypedClient(responses=[_typed_success(), _typed_success(), _typed_success(), _typed_success()])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
    )
    planned = engine.plan_activates_reachable(root.id)
    assert set(planned) == {root.id, left.id, right.id, sink.id}

    _, _, results = engine.execute_activates_reachable(root.id, request="execute grafo")
    assert len(results) == 4
    assert all(r.success for r in results)


def test_execute_activates_parallel_records_collaboration_edges_for_successful_branches() -> None:
    graph = CognitiveGraph()
    root = SynapseNode.specialist(
        "Root",
        role="framer",
        objective="root",
        output_contract_model=SynapseOutput,
    )
    left = SynapseNode.specialist(
        "Left",
        role="explorer",
        objective="left",
        output_contract_model=SynapseOutput,
    )
    right = SynapseNode.specialist(
        "Right",
        role="explorer",
        objective="right",
        output_contract_model=SynapseOutput,
    )
    for node in (root, left, right):
        graph.add_node(node)
    graph.add_edge(GraphEdge.connect(root.id, left.id, EdgeKind.ACTIVATES, weight=0.9))
    graph.add_edge(GraphEdge.connect(root.id, right.id, EdgeKind.ACTIVATES, weight=0.85))

    client = FakeTypedClient(responses=[_typed_success(), _typed_success(), _typed_success()])
    engine = ExecutionEngine(
        graph=graph,
        llm_client=client,
        model_registry={"SynapseOutput": SynapseOutput},
    )
    _, _, results = engine.execute_activates_parallel(root.id, request="execute paralelo")

    assert len(results) == 3
    forward = None
    backward = None
    for edge in graph.iter_edges_from(left.id, kinds=[EdgeKind.COLLABORATED_WITH], active_only=False):
        if edge.target_id == right.id:
            forward = edge
    for edge in graph.iter_edges_from(right.id, kinds=[EdgeKind.COLLABORATED_WITH], active_only=False):
        if edge.target_id == left.id:
            backward = edge

    assert forward is not None
    assert backward is not None
    assert forward.successes == 1
    assert backward.successes == 1


def test_execute_synapse_tooling_runs_dynamic_module_without_llm() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        module_path = Path(tmp) / "connector_runtime.py"
        module_path.write_text(
            """from __future__ import annotations

def run(payload):
    return {
        "status": "executed",
        "capability_id": payload.get("capability_id", ""),
        "request_size": len(str(payload.get("request", ""))),
    }
""",
            encoding="utf-8",
        )

        graph = CognitiveGraph()
        synapse = SynapseNode.specialist(
            "Tool Runner",
            role="operator",
            objective="executar ferramenta dinâmica",
            action="execute_tooling",
            capability_id="connector.runtime",
            module_path=str(module_path),
        )
        graph.add_node(synapse)
        engine = ExecutionEngine(graph=graph, llm_client=FakeTypedClient(responses=[]))
        ctx = StepContext()

        result = engine.execute_synapse(synapse.id, request="executar ferramenta", context=ctx)

        assert result.success is True
        assert result.output["status"] == "executed"
        assert result.output["capability_id"] == "connector.runtime"
        assert synapse.id in ctx.outputs
        assert len(ctx.errors) == 0
        updated = graph.get_node(synapse.id)
        assert updated is not None
        assert updated.stats.successes == 1


def test_execute_synapse_tooling_receives_enriched_context_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        module_path = Path(tmp) / "connector_runtime_context.py"
        module_path.write_text(
            """from __future__ import annotations

def run(payload):
    ctx = payload.get("context", {}) or {}
    return {
        "status": "executed",
        "context_keys": sorted(list(ctx.keys())),
        "has_recent_outputs": bool(ctx.get("recent_outputs")),
        "has_related_outputs": isinstance(ctx.get("related_outputs"), list),
        "context_version": ctx.get("context_version", 0),
    }
""",
            encoding="utf-8",
        )

        graph = CognitiveGraph()
        synapse = SynapseNode.specialist(
            "Tool Runner Context",
            role="operator",
            objective="executar ferramenta dinâmica com contexto",
            action="execute_tooling",
            capability_id="connector.runtime",
            module_path=str(module_path),
        )
        graph.add_node(synapse)
        engine = ExecutionEngine(graph=graph)
        ctx = StepContext()
        ctx.write("syn_prev", {"status": "planned"}, action="decompose_work", agent_id="planner", channel="llm")

        result = engine.execute_synapse(synapse.id, request="executar ferramenta", context=ctx)

        assert result.success is True
        assert result.output["has_recent_outputs"] is True
        assert result.output["has_related_outputs"] is True
        assert result.output["context_version"] >= 1
        assert "recent_outputs" in result.output["context_keys"]
        assert "recent_tool_outputs" in result.output["context_keys"]
        assert "related_outputs" in result.output["context_keys"]


def test_execute_synapse_tooling_fails_when_module_missing() -> None:
    graph = CognitiveGraph()
    synapse = SynapseNode.specialist(
        "Tool Runner Missing",
        role="operator",
        objective="executar ferramenta dinâmica",
        action="execute_tooling",
        capability_id="connector.missing",
        module_path="C:/nao/existe/connector.py",
    )
    graph.add_node(synapse)
    engine = ExecutionEngine(graph=graph, strict_real=False)
    ctx = StepContext()

    result = engine.execute_synapse(synapse.id, request="executar ferramenta", context=ctx)

    assert result.success is False
    assert "module_path_not_found" in (result.error or "")
    assert len(ctx.errors) == 1
    updated = graph.get_node(synapse.id)
    assert updated is not None
    assert updated.stats.failures == 1


def test_downstream_llm_receives_structured_recent_tool_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        module_path = Path(tmp) / "connector_runtime.py"
        module_path.write_text(
            """from __future__ import annotations

def run(payload):
    return {
        "status": "executed",
        "capability_id": payload.get("capability_id", ""),
        "result": {"ok": True},
    }
""",
            encoding="utf-8",
        )

        graph = CognitiveGraph()
        tool_syn = SynapseNode.specialist(
            "Tool Runner",
            role="operator",
            objective="executar ferramenta dinâmica",
            action="execute_tooling",
            capability_id="connector.runtime",
            module_path=str(module_path),
        )
        llm_syn = SynapseNode.specialist(
            "Critic",
            role="critic",
            objective="avaliar resultado da execução da ferramenta",
            output_contract_model=SynapseOutput,
            capability_id="connector.runtime",
        )
        graph.add_node(tool_syn)
        graph.add_node(llm_syn)
        graph.add_edge(GraphEdge.connect(tool_syn.id, llm_syn.id, EdgeKind.ACTIVATES, weight=0.95))

        client = FakeTypedClient(responses=[_typed_success()])
        engine = ExecutionEngine(
            graph=graph,
            llm_client=client,
            model_registry={"SynapseOutput": SynapseOutput},
        )
        path, _, results = engine.execute_activates_chain(tool_syn.id, request="execute e avalie")

        assert path == [tool_syn.id, llm_syn.id]
        assert len(results) == 2
        assert len(client.calls) == 1
        messages = client.calls[0]["messages"]
        assert isinstance(messages, list)
        user_content = str(messages[-1]["content"])
        assert "Saidas de ferramentas recentes" in user_content
        assert "connector.runtime" in user_content
        assert "Contexto relacionado (acao/capability)" in user_content
