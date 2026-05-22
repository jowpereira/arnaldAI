# RTK — Guia Completo de Instalação e Configuração (Windows + Binário)

> **O que é:** CLI proxy escrito em Rust que intercepta outputs de comandos de terminal
> e os comprime/filtra antes de chegarem ao contexto do LLM (Copilot, Codex, etc).
>
> **Por que usar:** Agentes de IA consomem tokens lendo outputs de terminal. Um simples
> `git status` gera ~2.000 tokens de texto bruto. Com RTK, cai para ~200 tokens.
> Em sessões de 30 minutos, a economia total chega a 80% dos tokens de terminal.
>
> **Como funciona:** Você prefixe comandos com `rtk` (ex: `rtk git status`).
> O RTK executa o comando real, filtra o output (remove ruído, agrupa, trunca, deduplica)
> e devolve uma versão compacta. O LLM recebe menos texto, gasta menos tokens, e responde
> mais rápido. Overhead: <10ms por comando.
>
> Repo: <https://github.com/rtk-ai/rtk>

---

## Pré-requisitos

- Windows 10 ou 11 (64-bit)
- PowerShell 5.1+ ou Windows Terminal
- VS Code com GitHub Copilot (para seção 4) e/ou Codex CLI (para seção 5)
- Acesso à internet (para baixar o binário)

---

## 1. Download do binário

### Passo 1.1 — Acessar a página de releases

Abra no navegador: <https://github.com/rtk-ai/rtk/releases>

Você verá uma lista de versões. A primeira da lista é a mais recente (ex: `v0.40.0`).

### Passo 1.2 — Baixar o ZIP correto

Na seção "Assets" da release mais recente, procure:

```text
rtk-x86_64-pc-windows-msvc.zip
```

Clique para baixar. O arquivo tem ~5-10 MB.

> **Dica:** Se seu Windows for ARM (Surface Pro X, etc.), procure por
> `rtk-aarch64-pc-windows-msvc.zip` — mas isso é raro, a maioria é x86_64.

### Passo 1.3 — Extrair o arquivo

1. Vá até a pasta de Downloads (`C:\Users\<seu-usuario>\Downloads`)
2. Clique com botão direito no ZIP → "Extrair tudo..." (ou use 7-Zip/WinRAR)
3. Dentro da pasta extraída você encontrará o arquivo `rtk.exe`

Resultado: você tem um arquivo `rtk.exe` (~15 MB) pronto para usar.

---

## 2. Colocar o `rtk.exe` no PATH do sistema

O PATH é a lista de diretórios onde o Windows procura executáveis.
Se o `rtk.exe` não estiver numa pasta do PATH, você precisaria digitar o caminho
completo toda vez (ex: `C:\Users\joao\Downloads\rtk.exe git status`) — impraticável.

### Passo 2.1 — Criar uma pasta dedicada para binários (recomendado)

Abra o PowerShell e execute:

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.local\bin"
```

Isso cria a pasta `C:\Users\<seu-usuario>\.local\bin\`. Se já existir, não faz nada.

### Passo 2.2 — Mover o rtk.exe para essa pasta

```powershell
# Ajuste o caminho de origem se necessário
Move-Item "$env:USERPROFILE\Downloads\rtk-x86_64-pc-windows-msvc\rtk.exe" "$env:USERPROFILE\.local\bin\rtk.exe"
```

> Se deu erro de "arquivo não encontrado", verifique o nome exato da pasta extraída.
> Use `Get-ChildItem "$env:USERPROFILE\Downloads\rtk*"` para listar.

### Passo 2.3 — Adicionar a pasta ao PATH do usuário (permanente)

```powershell
$binPath = "$env:USERPROFILE\.local\bin"
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")

# Verificar se já está no PATH
if ($currentPath -notlike "*$binPath*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentPath;$binPath", "User")
    Write-Host "PATH atualizado com sucesso. Reinicie o terminal." -ForegroundColor Green
} else {
    Write-Host "Pasta já está no PATH." -ForegroundColor Yellow
}
```

### Passo 2.4 — Reiniciar o terminal

**OBRIGATÓRIO.** Feche TODOS os terminais abertos (PowerShell, cmd, Windows Terminal)
e abra um novo. Variáveis de ambiente só carregam em sessões novas.

> **Alternativa rápida** (sem reiniciar, só para a sessão atual):
> ```powershell
> $env:Path += ";$env:USERPROFILE\.local\bin"
> ```
> Mas isso é temporário — some ao fechar o terminal.

---

## 3. Verificar a instalação

### Passo 3.1 — Checar versão

```powershell
rtk --version
```

**Saída esperada:**

```text
rtk 0.40.0
```

Se aparecer "rtk: command not found" ou "não reconhecido como comando", significa que:
- O terminal não foi reiniciado (feche e abra novo)
- O PATH não foi atualizado corretamente (execute o passo 2.3 novamente)
- O `rtk.exe` não está na pasta certa (execute `Test-Path "$env:USERPROFILE\.local\bin\rtk.exe"`)

### Passo 3.2 — Checar estatísticas

```powershell
rtk gain
```

**Saída esperada (primeiro uso):**

```text
RTK Token Savings
─────────────────
Commands tracked: 0
Tokens saved: 0
```

Após usar por um tempo, mostrará economia acumulada.

### Passo 3.3 — Testar um comando filtrado

```powershell
rtk git status
```

**Saída esperada** (output compacto do git status):

```text
M  arnaldo/core.py
M  tests/test_kernel.py
?? docs/rtk-setup-guide.md
```

Compare com `git status` puro (que gera ~20 linhas com headers, branch info, etc).

> **NUNCA dê duplo-clique no rtk.exe.** Ele é uma ferramenta de linha de comando.
> Se você clicar duas vezes, uma janela preta vai piscar e fechar — é o comportamento
> normal de um CLI sem argumentos. Sempre use pelo terminal.

---

## 4. Configurar para VS Code Copilot

### O que vamos fazer

O GitHub Copilot em Agent Mode (Chat com `@workspace` ou modo agente) executa comandos
de terminal automaticamente. Queremos que ele prefixe TUDO com `rtk` para economizar tokens.

Existem dois mecanismos:
1. **Hook automático** — intercepta comandos antes de executar (só funciona em Bash/Linux/Mac)
2. **Instrução textual** — diz ao agente "sempre prefixe com rtk" (funciona em qualquer OS)

No Windows, usaremos **ambos** — o `rtk init` tenta o hook (que não vai funcionar) mas
também cria arquivos de instrução que o Copilot lê.

### Passo 4.1 — Executar rtk init para Copilot

Abra o terminal na raiz do seu projeto e execute:

```powershell
rtk init -g --copilot
```

**O que esse comando faz:**

| Ação | Arquivo criado/modificado | Localização |
| ---- | ------------------------- | ----------- |
| Instruções globais para o agente | `RTK.md` | `~/.config/rtk/RTK.md` ou similar |
| Referência no settings | `.vscode/settings.json` | Raiz do projeto |
| Tentativa de hook (falha no Windows) | — | — |

### Passo 4.2 — Verificar o que foi criado

```powershell
rtk init --show
```

**Saída esperada:**

```text
rtk Configuration:

[OK] RTK.md: found
[OK] settings.json: found
[--] Hook: not found              ← Esperado no Windows!
```

O `[--] Hook: not found` é **normal** no Windows. O hook de reescrita automática precisa
de Bash e não funciona em PowerShell/cmd.

### Passo 4.3 — Criar instrução explícita no projeto (ESSENCIAL no Windows)

Como o hook não funciona no Windows, precisamos de uma instrução textual que o Copilot
vai ler toda vez que abrir uma sessão no projeto.

Crie o arquivo `.github/instructions/rtk.instructions.md` com o seguinte conteúdo:

```markdown
---
applyTo: "**"
description: "Instrui o agente a prefixar todos os comandos de terminal com rtk para economia de tokens"
---

# RTK — Token-Optimized CLI

**rtk** is a CLI proxy that filters and compresses command outputs, saving 60-90% tokens.

## Rule

Always prefix shell commands with `rtk`:

| Instead of | Use |
| ---------- | --- |
| git status | rtk git status |
| git log -10 | rtk git log -10 |
| git diff | rtk git diff |
| git add . | rtk git add . |
| git commit -m "msg" | rtk git commit -m "msg" |
| git push | rtk git push |
| pytest -x -v | rtk pytest -x -v |
| uv run pytest | rtk uv run pytest |
| uv run ruff check . | rtk uv run ruff check . |
| uv run mypy . | rtk uv run mypy . |
| pip list | rtk pip list |
| docker ps | rtk docker ps |
| docker logs <c> | rtk docker logs <c> |

## Exceptions (do NOT prefix)

- Interactive commands: python REPL, ipython, vim, nano
- Package installs: pip install, uv add, npm install (output not needed by LLM)
- Trivial commands: cd, mkdir, echo, rm, mv, cp

## Meta commands (use directly, no prefix needed)

- `rtk gain` — token savings dashboard
- `rtk gain --history` — per-command savings history
- `rtk discover` — find missed rtk opportunities
- `rtk proxy <cmd>` — run without filtering but track usage
```

> **Por que isso funciona:** O VS Code Copilot carrega automaticamente todos os arquivos
> em `.github/instructions/` como contexto do agente. O campo `applyTo: "**"` garante
> que é carregado para qualquer arquivo que estiver aberto.

### Passo 4.4 — Testar no Copilot

1. Abra o VS Code
2. Abra o Chat (Ctrl+Shift+I ou ícone de chat)
3. Selecione o modo **Agent** (não o modo Ask)
4. Peça algo como: "rode os testes do projeto"
5. O Copilot deve executar `rtk uv run pytest -x -v` (com prefixo rtk)

Se o Copilot NÃO usar `rtk`, verifique:
- O arquivo `.github/instructions/rtk.instructions.md` existe e está commitado?
- Reiniciou o VS Code depois de criar?
- O modo é Agent (não Ask ou Edit)?

---

## 5. Configurar para Codex (OpenAI)

### O que é o Codex

O Codex (OpenAI) é um agente CLI que roda no terminal. Ele lê um arquivo `AGENTS.md`
para saber regras e convenções do projeto. Vamos inserir as instruções RTK nele.

### Passo 5.1 — Executar rtk init para Codex

```powershell
# Global (aplica para TODOS os projetos que usar com Codex)
rtk init -g --codex
```

**O que faz:**

| Ação | Resultado |
| ---- | --------- |
| Cria/atualiza `AGENTS.md` | Em `~/.codex/AGENTS.md` (global) |
| Cria `RTK.md` referenciado | Em `~/.codex/RTK.md` |
| Inclui instrução de prefixo | Codex lê AGENTS.md automaticamente |

**Alternativa — apenas no projeto atual (não global):**

```powershell
rtk init --codex
```

Nesse caso cria `AGENTS.md` e `RTK.md` na raiz do repositório.

### Passo 5.2 — Verificar

```powershell
rtk init --show
```

Deve mostrar algo como:

```text
[OK] RTK.md: found
[OK] AGENTS.md: found (codex)
```

### Passo 5.3 — Testar no Codex

```powershell
codex "rode os testes"
```

O Codex deve usar `rtk pytest` ou `rtk uv run pytest` ao invés do comando puro.

---

## 6. Confirmar economia após uso

Depois de usar por alguns minutos (ou uma sessão inteira), verifique os ganhos:

### Passo 6.1 — Dashboard geral

```powershell
rtk gain
```

**Saída exemplo após uso:**

```text
RTK Token Savings
─────────────────
Commands tracked: 47
Raw tokens: 94,200
Filtered tokens: 18,840
Tokens saved: 75,360 (80%)
Estimated cost saved: $0.15
```

### Passo 6.2 — Histórico por comando

```powershell
rtk gain --history
```

**Saída exemplo:**

```text
Recent commands:
  rtk git status          → saved 1,600 tokens (80%)
  rtk uv run pytest -x -v → saved 7,200 tokens (90%)
  rtk git diff            → saved 3,500 tokens (75%)
  rtk git log -5          → saved 2,000 tokens (80%)
```

### Passo 6.3 — Encontrar oportunidades perdidas

```powershell
rtk discover
```

**Saída exemplo:**

```text
Missed opportunities (last 24h):
  git status (called 3x without rtk) → could save ~4,800 tokens
  pytest (called 1x without rtk) → could save ~8,000 tokens

Tip: add these to your workflow or check your instructions file.
```

---

## 7. Uso no dia-a-dia — Referência completa

### Comandos Git

```powershell
rtk git status              # Output compacto (só arquivos modificados)
rtk git log -10             # Uma linha por commit
rtk git diff                # Diff condensado (sem headers repetitivos)
rtk git add .               # Retorna "ok" (em vez de listar cada arquivo)
rtk git commit -m "msg"     # Retorna "ok abc1234" (hash do commit)
rtk git push                # Retorna "ok main" (branch pushado)
rtk git pull                # Retorna "ok 3 files +10 -2" (resumo)
```

### Comandos de teste

```powershell
rtk uv run pytest -x -v     # Só mostra falhas (economia de ~90%)
rtk uv run pytest            # Idem
rtk pytest                   # Se pytest está no PATH
```

### Linting e type-checking

```powershell
rtk uv run ruff check arnaldo/ tests/   # Erros agrupados por regra
rtk uv run ruff format arnaldo/ tests/  # Output mínimo
rtk uv run mypy arnaldo/               # Erros agrupados por arquivo
```

### Arquivos e diretórios

```powershell
rtk ls .                    # Árvore compacta (sem detalhes de permissão)
rtk read arquivo.py         # Leitura inteligente (com numeração de linha)
rtk find "*.py" .           # Resultado compacto
rtk grep "pattern" .        # Resultados agrupados por arquivo
```

### Docker e containers

```powershell
rtk docker ps               # Lista compacta de containers
rtk docker images           # Lista compacta de imagens
rtk docker logs <container> # Logs deduplicados
```

### Outros

```powershell
rtk pip list                # Pacotes instalados (auto-detecta uv)
rtk pip outdated            # Pacotes desatualizados
rtk curl <url>              # Trunca resposta + salva completa
```

### O que NÃO prefixar com rtk

| Comando | Por que não |
| ------- | ----------- |
| `python` (REPL) | Interativo — rtk não sabe quando termina |
| `ipython` | Idem |
| `pip install X` | Output de instalação não vai pro LLM |
| `uv add X` | Idem |
| `npm install` | Idem |
| `cd`, `mkdir`, `echo` | Output já é mínimo, sem ganho |
| `code .` | Abre GUI, não produz output |

### Meta-comandos RTK (usar direto, SEM prefixar)

```powershell
rtk gain                    # Dashboard de economia total
rtk gain --graph            # Gráfico ASCII dos últimos 30 dias
rtk gain --history          # Histórico dos últimos comandos
rtk gain --daily            # Breakdown dia-a-dia
rtk gain --all --format json # Export JSON (para dashboards)
rtk discover                # Oportunidades perdidas
rtk discover --all --since 7 # Todos os projetos, últimos 7 dias
rtk session                 # Adoção RTK nas sessões recentes
rtk proxy <cmd>             # Rodar SEM filtro mas rastreando tokens
```

---

## 8. Configuração avançada (opcional)

### Onde fica o arquivo de config

No Windows: `%APPDATA%\rtk\config.toml`

Caminho completo típico: `C:\Users\<usuario>\AppData\Roaming\rtk\config.toml`

Se o arquivo não existir, crie-o manualmente:

```powershell
New-Item -ItemType Directory -Force -Path "$env:APPDATA\rtk"
New-Item -ItemType File -Path "$env:APPDATA\rtk\config.toml"
```

### Conteúdo do config.toml

```toml
# Comandos que NUNCA devem ser reescritos pelo hook (mesmo em Linux/Mac)
[hooks]
exclude_commands = ["curl", "playwright", "python"]

# Salvamento automático de output bruto quando comando falha
[tee]
enabled = true          # Salvar output completo em caso de falha
mode = "failures"       # Opções: "failures" | "always" | "never"
                        # "failures" = só salva se exit code != 0
                        # "always" = salva tudo (usa mais disco)
                        # "never" = nunca salva
```

### Como funciona o tee (output de falhas)

Quando um comando falha (exit code != 0), o RTK salva o output completo sem filtrar.
Isso é útil porque a versão filtrada pode omitir detalhes relevantes para debug.

Exemplo de saída filtrada com referência ao log completo:

```text
FAILED: 2/15 tests
  test_edge_case: assertion failed (expected 42, got 0)
  test_overflow: panic at utils.rs:18

[full output: C:\Users\<usuario>\AppData\Local\rtk\tee\1707753600_pytest.log]
```

O agente (Copilot/Codex) pode ler esse arquivo se precisar de mais contexto.

---

## 9. Troubleshooting

### "rtk não é reconhecido como comando"

**Causa:** O `rtk.exe` não está no PATH, ou o terminal não foi reiniciado.

**Solução:**

```powershell
# 1. Verificar se o arquivo existe
Test-Path "$env:USERPROFILE\.local\bin\rtk.exe"
# Deve retornar True

# 2. Verificar se a pasta está no PATH
$env:Path -split ";" | Where-Object { $_ -like "*\.local\bin*" }
# Deve mostrar a pasta

# 3. Se não estiver, adicionar novamente
$binPath = "$env:USERPROFILE\.local\bin"
[Environment]::SetEnvironmentVariable("Path", "$([Environment]::GetEnvironmentVariable('Path','User'));$binPath", "User")

# 4. Reiniciar o terminal (OBRIGATÓRIO)
```

### "rtk gain mostra 0 tokens salvos"

**Causa:** Você está usando comandos sem o prefixo `rtk`, ou acabou de instalar.

**Solução:** Certifique-se de prefixar TODOS os comandos. Use `rtk discover` para ver o que está escapando.

### "Copilot não usa rtk"

**Causas possíveis:**

1. O arquivo `.github/instructions/rtk.instructions.md` não existe
2. O VS Code não foi reiniciado após criar o arquivo
3. Você está no modo "Ask" em vez de "Agent"
4. O arquivo tem erro de sintaxe no frontmatter YAML

**Verificação:**

```powershell
# Verificar se o arquivo existe
Test-Path ".github\instructions\rtk.instructions.md"

# Verificar o frontmatter (primeiras 4 linhas)
Get-Content ".github\instructions\rtk.instructions.md" -First 4
# Deve mostrar:
# ---
# applyTo: "**"
# description: "..."
# ---
```

### "rtk git push deu erro"

**Causa:** O RTK filtra o OUTPUT, não o comando. Se `git push` falha, o erro é do git.
O RTK apenas compactou a mensagem de erro.

**Solução:** Use `rtk proxy git push` para ver o output completo sem filtro.
Ou verifique o log tee se `[tee]` estiver habilitado.

### "Output filtrado demais, perdi informação"

**Solução temporária:** Use `rtk proxy <comando>` para rodar sem filtro.

**Solução permanente:** Adicione o comando ao `exclude_commands` no config.toml:

```toml
[hooks]
exclude_commands = ["curl", "playwright", "comando-problematico"]
```

---

## 10. Desinstalar

### Passo 10.1 — Remover configurações do agente

```powershell
rtk init -g --uninstall
```

Isso remove:
- `RTK.md` criado pelo `rtk init`
- Entrada no `.vscode/settings.json`
- `AGENTS.md` e `RTK.md` do Codex (se existirem)
- Hook (se existir — no Windows geralmente não tem)

### Passo 10.2 — Remover a instrução do projeto (manual)

```powershell
Remove-Item ".github\instructions\rtk.instructions.md"
```

### Passo 10.3 — Remover o binário

```powershell
Remove-Item "$env:USERPROFILE\.local\bin\rtk.exe"
```

### Passo 10.4 — (Opcional) Remover a pasta do PATH

Só faça isso se não tiver mais nada em `.local\bin`:

```powershell
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
$newPath = ($currentPath -split ";" | Where-Object { $_ -notlike "*\.local\bin*" }) -join ";"
[Environment]::SetEnvironmentVariable("Path", $newPath, "User")
```

---

## 11. Economia esperada

### Por comando

| Comando | Output bruto (tokens) | Com RTK (tokens) | Economia |
| ------- | --------------------- | ---------------- | -------- |
| `git status` | ~2.000 | ~400 | -80% |
| `git diff` | ~10.000 | ~2.500 | -75% |
| `git log -10` | ~2.500 | ~500 | -80% |
| `git add/commit/push` | ~1.600 | ~120 | -92% |
| `pytest` | ~8.000 | ~800 | -90% |
| `ruff check` | ~3.000 | ~600 | -80% |
| `ls / tree` | ~800 | ~150 | -80% |
| `cat / read` | ~2.000 | ~600 | -70% |

### Sessão típica de 30 minutos

| Métrica | Sem RTK | Com RTK |
| ------- | ------- | ------- |
| Tokens de terminal consumidos | ~118.000 | ~24.000 |
| Economia total | — | **~80%** |
| Custo estimado economizado (GPT-4) | — | ~$0.10-$0.30 |

> Valores são estimativas baseadas em projetos de tamanho médio (Python/TypeScript).
> A economia real varia com o tamanho do projeto e frequência de comandos.

---

## Resumo rápido (TL;DR)

```powershell
# ──── INSTALAÇÃO ────
# 1. Baixar rtk-x86_64-pc-windows-msvc.zip de:
#    https://github.com/rtk-ai/rtk/releases

# 2. Extrair e mover para PATH:
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.local\bin"
Move-Item .\rtk.exe "$env:USERPROFILE\.local\bin\rtk.exe"
$p = [Environment]::GetEnvironmentVariable("Path","User")
[Environment]::SetEnvironmentVariable("Path","$p;$env:USERPROFILE\.local\bin","User")
# Reiniciar terminal!

# ──── CONFIGURAÇÃO ────
# 3. Para VS Code Copilot:
rtk init -g --copilot
# + criar .github/instructions/rtk.instructions.md (ver seção 4.3)

# 4. Para Codex:
rtk init -g --codex

# ──── VERIFICAÇÃO ────
rtk --version           # rtk 0.40.0
rtk init --show         # [OK] nos itens configurados
rtk git status          # Testar filtragem
rtk gain                # Ver economia (0 no início, cresce com uso)
```
rtk gain
```
