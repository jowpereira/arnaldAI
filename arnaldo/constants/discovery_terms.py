"""Termos de descoberta local — fonte canônica para classify e planner."""

from __future__ import annotations

# Verbos de ação que indicam interação com o filesystem/shell local.
# Usados pelo classify.py (com word boundaries) e adaptive_planner.py (substring).
FILESYSTEM_DISCOVERY_VERBS: tuple[str, ...] = (
    "ache",
    "encontre",
    "localize",
    "procure",
    "busque",
    "liste",
    "listar",
    "verifique",
    "cheque",
    "descubra",
)

SHELL_EXECUTION_VERBS: tuple[str, ...] = (
    "rode",
    "execute",
    "rodar",
    "executar",
)

# Substantivos que contextualizam descoberta local (co-ocorrência obrigatória).
LOCAL_CONTEXT_NOUNS: tuple[str, ...] = (
    "pasta",
    "arquivo",
    "diretório",
    "diretorio",
    "instalado",
    "instalação",
    "instalacao",
    "caminho",
    "path",
    "disco",
)

SHELL_CONTEXT_NOUNS: tuple[str, ...] = (
    "powershell",
    "terminal",
    "cmd",
    "shell",
    "comando",
)

# Verbos genéricos que SÓ indicam execução quando acompanhados de contexto técnico.
# Sem co-ocorrência, são falso-positivos ("criar coragem", "sistema solar").
AMBIGUOUS_VERBS: tuple[str, ...] = (
    "criar",
    "abrir",
    "mostrar",
)

# Contexto técnico que desambigua verbos genéricos.
TECHNICAL_CONTEXT: tuple[str, ...] = (
    "api",
    "ferramenta",
    "código",
    "codigo",
    "projeto",
    "arquivo",
    "pasta",
    "diretório",
    "diretorio",
    "terminal",
    "script",
    "servidor",
    "banco",
    "dados",
    "sistema operacional",
    "app",
    "aplicação",
    "aplicacao",
    "programa",
    "container",
    "docker",
    "pipeline",
    "deploy",
    "config",
)

# Todos os termos de descoberta local (union para planner substring match).
ALL_LOCAL_DISCOVERY_TERMS: tuple[str, ...] = (
    *FILESYSTEM_DISCOVERY_VERBS,
    *SHELL_EXECUTION_VERBS,
    *LOCAL_CONTEXT_NOUNS,
    *SHELL_CONTEXT_NOUNS,
)

# Prefixos que identificam capabilities de tooling (fonte canônica).
TOOLING_PREFIXES: tuple[str, ...] = ("connector.", "tool.", "search.", "filesystem.", "shell.")

# Subconjunto: capabilities que executam localmente (filesystem + shell).
LOCAL_CAPABILITY_PREFIXES: tuple[str, ...] = ("filesystem.", "shell.")
