# Minimo Para Rodar

Este corte roda sem dependencias externas e sem chave de API.

```powershell
python -m arnaldo "Crie um plano inicial para uma ferramenta B2B de automacao"
```

O lema deste corte e **100% generico**: mesmo quando o pedido cita um dominio, o nucleo nao vira um assistente daquele dominio. Ele compila a intencao em contratos genericos e executa um runtime local.

Saidas principais:

- `runs/<run_id>/intent-ir.json`: intencao declarativa.
- `runs/<run_id>/task-ir.json`: representacao intermediaria da tarefa.
- `runs/<run_id>/cognitive-decision.json`: modo cognitivo escolhido.
- `runs/<run_id>/capability-resolution.json`: capacidades disponiveis e ausentes.
- `runs/<run_id>/organization-ir.json`: organizacao temporaria gerada.
- `runs/<run_id>/policy-decision.json`: decisao de politica.
- `runs/<run_id>/trace.jsonl`: eventos do runtime.
- `runs/<run_id>/evidence.jsonl`: ledger append-only.
- `runs/<run_id>/artifact.md`: artefato produzido.
- `runs/<run_id>/result.md`: resumo da execucao.

```text
intencao -> Intent IR -> Task IR -> decisao cognitiva -> capacidades -> organizacao -> politica -> runtime -> evidencia -> artefato
```

Ainda nao ha chamada de LLM, execucao de ferramentas externas, memoria persistente ou runtime multiagente real.

Veja tambem [`docs/arquitetura.md`](arquitetura.md).
