---
applyTo: "tests/**"
description: "Padrões para escrita de testes no ArnaldAI — pytest com uv"
---

# Testes — Padrões do ArnaldAI

## Estrutura

```
tests/
├── __init__.py
├── support_llm.py               ← Helpers para testes com LLM (mocks, skips)
├── test_kernel.py               ← Testes do kernel principal
├── test_graph.py                ← Testes do grafo cognitivo
├── test_graph_execution.py      ← Testes de execução em grafo
├── test_graph_refs.py           ← Testes de GraphRef (hierarquia)
├── test_graph_workflows.py      ← Testes de workflows
├── test_graph_runtime_integration.py ← Integração runtime + grafo
├── test_memory_store.py         ← Testes do MemoryStore
├── test_tool_forge.py           ← Testes de forja de ferramentas
├── test_adaptive_planner.py     ← Testes do planejador adaptativo
├── test_adaptive_kernel.py      ← Testes do kernel adaptativo
├── test_multiagent_runtime.py   ← Testes do runtime multi-agente
├── test_proactivity.py          ← Testes de proatividade
├── test_structured.py           ← Testes de saídas estruturadas LLM
├── test_llm_integration.py      ← Testes de integração LLM (requer Azure)
├── test_cli.py                  ← Testes da CLI
├── test_contract_registry.py    ← Testes do registro de contratos
└── test_dynamic_features.py     ← Testes de features dinâmicas
```

## Convenções

- **Arquivo:** `test_<módulo>.py`
- **Classe:** `Test<Funcionalidade>` (agrupamento lógico)
- **Método:** `test_<ação>_<resultado_esperado>_<condição>`
- **Padrão:** Arrange → Act → Assert (AAA)

## Execução

```bash
# Todos os testes
uv run pytest -x -v

# Teste específico
uv run pytest tests/test_graph.py -v

# Com cobertura
uv run pytest --cov=arnaldo --cov-report=term-missing

# Apenas marcados
uv run pytest -m "not slow"

# Verbose com traceback curto
uv run pytest -x -v --tb=short
```

## Padrões de Teste

### Teste unitário básico

```python
def test_node_creation_preserves_kind():
    """Criação de nó preserva o kind tipado."""
    node = MemoryNode(kind=NodeKind.EPISODIC, content="test")
    assert node.kind == NodeKind.EPISODIC
    assert node.content == "test"
```

### Teste com grafo

```python
def test_add_edge_respects_plasticity_bounds():
    """Peso de aresta nunca ultrapassa ceiling."""
    graph = CognitiveGraph()
    n1 = graph.add_node(MemoryNode(kind=NodeKind.EPISODIC, content="a"))
    n2 = graph.add_node(MemoryNode(kind=NodeKind.EPISODIC, content="b"))
    edge = graph.add_edge(n1, n2, kind=EdgeKind.ACTIVATES, weight=0.5)

    # Reforço repetido não ultrapassa ceiling
    for _ in range(100):
        graph.reinforce(edge)

    assert graph.get_weight(edge) <= 1.0
```

### Teste com mock de LLM

```python
from tests.support_llm import mock_llm_response

def test_intent_compiler_with_llm_failure_uses_heuristic():
    """Fallback heurístico quando LLM falha."""
    compiler = IntentCompiler(llm_client=None)
    result = compiler.compile("Crie um plano")
    assert result is not None  # heurística nunca falha
```

## Regras

- **Sem dependências externas nos testes unitários** — testes rodam offline
- **Testes de LLM marcados** com `@pytest.mark.llm` ou skip condicional
- **Fixtures mínimas** — setup simples, sem over-engineering
- **Um assert por cenário** — cada test case valida UMA coisa
- **Nome descritivo** — `test_sweep_decay_reduces_weight_by_half_life`, não `test_1`
- **Rode com `-x`** — pare no primeiro erro
- **NUNCA `@pytest.mark.skip` sem justificativa** — skip é confissão de derrota

## Cobertura Mínima Esperada

| Tipo | O que testar |
|------|-------------|
| **Grafo** | Criação de nós/arestas, tipagem, plasticidade, decay, proveniência |
| **Kernel** | Pipeline completo (compile → match → execute), fallback heurístico |
| **Runtime** | Execução de workflow, paralelismo, sandbox |
| **LLM** | Roteamento por tier, structured outputs, retry, refusal handling |
| **Memória** | Persistência, retrieval, candidatos de sinapse, materialização |
| **CLI** | Argumentos, output formatting, streaming |
