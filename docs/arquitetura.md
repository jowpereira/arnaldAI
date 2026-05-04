# Arquitetura Do Repositorio

Lema operacional: **100% generico**.

O Arnaldo nao deve crescer como um conjunto de agentes por dominio. Ele deve crescer como um compilador generico de trabalho:

```text
intencao -> contratos -> decisao cognitiva -> capacidades -> organizacao -> politica -> runtime -> evidencia -> artefato
```

## Camadas

- `arnaldo/contracts/`: IRs e contratos versionaveis.
- `arnaldo/components/`: componentes cognitivos puros.
- `arnaldo/runtime/`: adaptadores de execucao.
- `arnaldo/storage/`: persistencia local de runs.
- `arnaldo/kernel.py`: orquestrador do fluxo completo.
- `arnaldo/cli.py`: interface de linha de comando.

## Regra De Design

Dominios podem aparecer como contexto, dados, capacidade ou exemplos. Eles nao devem aparecer como arquitetura fixa do nucleo.

O nucleo deve responder a perguntas genericas:

- qual e a intencao?
- qual contrato executavel representa essa intencao?
- como o sistema deve pensar?
- quais capacidades sao necessarias?
- qual organizacao temporaria deve existir?
- qual politica permite ou bloqueia a execucao?
- quais evidencias provam o trabalho?

## Saida De Uma Run

Cada execucao gera uma pasta em `runs/<run_id>/`:

- `intent-ir.json`
- `task-ir.json`
- `cognitive-decision.json`
- `capability-resolution.json`
- `organization-ir.json`
- `policy-decision.json`
- `trace.jsonl`
- `evidence.jsonl`
- `artifact.md`
- `result.md`
