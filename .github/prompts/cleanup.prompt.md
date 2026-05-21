---
name: cleanup
description: "Varredura do codebase ArnaldAI: detecta e elimina código morto, imports não usados, módulos órfãos e lixo acumulado."
argument-hint: "Diretório ou escopo a limpar (ex: arnaldo/, tests/, arnaldo/graph/)"
agent: Arnaldo
tools: ['edit/createFile', 'edit/editFiles', 'edit/rename', 'search/codebase', 'search/fileSearch', 'search/textSearch', 'search/listDirectory', 'search/searchSubagent', 'search/usages', 'search/changes', 'read/readFile', 'read/problems', 'read/terminalLastCommand', 'read/terminalSelection', 'execute/runInTerminal', 'execute/getTerminalOutput', 'agent/runSubagent']
---

# Operação Limpeza — Aniquilação de Código Morto

Execute uma varredura profunda e paralela do codebase para identificar **todo lixo acumulado**.

> **⚠️ REGRA ABSOLUTA: Este prompt NÃO apaga NADA automaticamente.**
> Toda remoção exige aprovação explícita do usuário após leitura do relatório completo.

## Estratégia: Subagentes Paralelos

Lance **múltiplos subagentes `Explore`** em paralelo, cada um responsável por uma categoria de lixo. Aguarde todos os relatórios antes de executar qualquer remoção.

### Fase 1 — Reconhecimento (paralelo)

Lance simultaneamente os seguintes subagentes de pesquisa:

1. **Subagente: Imports Mortos**
   - Varra `arnaldo/**/*.py` e `tests/**/*.py`
   - Identifique imports que nunca são referenciados no corpo do módulo
   - Detecte `from X import *` desnecessários
   - Liste cada arquivo + linha + import morto

2. **Subagente: Código Morto**
   - Varra `arnaldo/**/*.py`
   - Detecte funções, classes e métodos **nunca chamados** no codebase
   - Detecte variáveis atribuídas mas nunca lidas
   - Detecte blocos `if False:`, `# TODO: remover`, código comentado extenso (>5 linhas)
   - Detecte arquivos `.py` com 0 referências externas (módulos órfãos)
   - Cruze com `__init__.py` exports — se exporta algo que ninguém importa, é morto

3. **Subagente: Arquivos Órfãos e Artifacts**
   - Identifique `*.txt` de output na raiz (`test_output.txt`, `build_output.txt`, etc.)
   - Identifique arquivos `.pyc`, `__pycache__/` fora de `.gitignore`
   - Identifique diretórios vazios ou com apenas `__init__.py` vazio
   - Identifique arquivos markdown em `docs/` que referenciam código/features que não existem mais

4. **Subagente: Violação de Regra 14 (>300 linhas)**
   - Varra `arnaldo/**/*.py` e `tests/**/*.py`
   - Liste todo arquivo com mais de 300 linhas — candidato a decomposição

### Fase 2 — Triagem

Consolide os relatórios dos subagentes e classifique cada item:

| Categoria | Ação |
|-----------|------|
| 🔴 **Lixo Confirmado** | Import morto, variável não usada, arquivo órfão sem referência |
| 🟡 **Provável Lixo** | Função sem caller direto (pode ser usada via reflexão/config) |
| 🟢 **Seguro (não mexer)** | Código em uso, referenciado em configs, testes, CI, ou docs ativos |

**Regras de segurança:**
- **NUNCA** remova algo que esteja em `pyproject.toml` como entry point, script ou dependência
- **NUNCA** remova arquivos referenciados em `.github/workflows/`
- **NUNCA** remova `__init__.py` que contenha exports usados
- **NUNCA** remova testes — mesmo que pareçam desatualizados
- **Na dúvida, NÃO remova** — classifique como 🟡 e pergunte

### Fase 3 — Relatório para Aprovação

Apresente o relatório completo ao usuário. **NÃO execute nenhuma remoção ainda.**

Formato do relatório:

```
## Relatório de Limpeza — Aguardando Aprovação

### 🔴 Lixo Confirmado (remoção recomendada)
Para cada item:
- Arquivo (com link)
- Linha(s) afetada(s)
- O que será removido (import, função, arquivo inteiro)
- Justificativa técnica

Subtotais:
- X imports mortos em Y arquivos
- Z funções/métodos nunca chamados
- W arquivos órfãos
- Total estimado: N linhas a remover

### 🟡 Provável Lixo (requer decisão manual)
Para cada item:
- Arquivo + contexto
- Por que parece lixo
- Por que pode NÃO ser lixo (reflexão, config dinâmica, etc.)

### 🟢 Mantidos (falsos positivos descartados)
- Justificativa para itens que pareciam lixo mas estão em uso
```

Após apresentar o relatório, **PARE e pergunte explicitamente:**

> "Relatório completo acima. O que deseja fazer?"
> 1. **Aprovar tudo (🔴)** — remove todos os itens confirmados
> 2. **Aprovar parcial** — indique quais itens ou categorias aprovar
> 3. **Revisar 🟡 juntos** — discutir os itens duvidosos antes de decidir
> 4. **Cancelar** — não remover nada

**Só prossiga para a Fase 4 após resposta explícita do usuário.**

### Fase 4 — Execução (somente após aprovação)

1. Remova **apenas** os itens aprovados pelo usuário, em batch por tipo:
   - Primeiro: imports mortos (menor risco, maior volume)
   - Segundo: variáveis/funções mortas
   - Terceiro: arquivos órfãos
2. Após cada batch, rode validação:
   - `uv run ruff check arnaldo/ tests/`
   - `uv run pytest -x -v --tb=short`
3. Se qualquer validação falhar, **reverta o batch inteiro** e informe o usuário

### Fase 5 — Relatório Final

Após execução, apresente o resumo do que foi efetivamente removido:

```
## Limpeza Concluída

### Removidos
- X imports mortos em Y arquivos
- Z funções/métodos eliminados
- W arquivos removidos
- Total: N linhas removidas

### Não Removidos (por decisão do usuário)
- Itens que o usuário optou por manter

### Validação
- ruff check: ✅/❌
- pytest: ✅/❌
```

## Notas

- Se o argumento especificar um diretório, limite a varredura a esse escopo
- Se nenhum argumento for passado, varra o **workspace inteiro**
- Priorize **volume de remoção** sem comprometer estabilidade
- Cada subagente deve retornar dados estruturados, não prosa
