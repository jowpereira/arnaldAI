# Path-Specific Instructions

Este diretório contém instruções específicas para diferentes tipos de arquivos e contextos no projeto.

## 📁 Estrutura

As instruções específicas por caminho permitem que você defina regras personalizadas para diferentes partes do seu código:

```
.github/instructions/
├── README.md                    # Este arquivo
├── typescript.instructions.md   # Instruções para arquivos TypeScript
└── python.instructions.md       # Instruções para arquivos Python
```

## 🎯 Como Funciona

Cada arquivo `.instructions.md` deve começar com um bloco frontmatter que define quais arquivos ele afeta:

```markdown
---
applyTo: "**/*.ts,**/*.tsx"
---

# Suas instruções aqui
```

### Padrões Glob Suportados

- `*` - Match todos os arquivos no diretório atual
- `**` - Match todos os arquivos em todos os diretórios
- `**/*.py` - Match todos os arquivos Python recursivamente
- `src/**/*.ts` - Match todos os arquivos TypeScript em src/
- `**/{*.test.ts,*.spec.ts}` - Match arquivos de teste

## 📝 Exemplos Prontos

Veja os arquivos de exemplo neste diretório para referência:

1. **typescript.instructions.md** - Padrões específicos de TypeScript
2. **python.instructions.md** - Convenções Python e type hints

## 🔄 Precedência

Quando múltiplos arquivos de instruções se aplicam:

1. Instruções específicas (path-specific) têm **maior prioridade**
2. Instruções do repositório (`.github/copilot-instructions.md`) são aplicadas como base
3. Em caso de conflito, o comportamento é **não-determinístico**

**Dica**: Evite conflitos entre instruções!

## 🚀 Criando Novas Instruções

Para criar instruções personalizadas:

1. Crie um arquivo `nome.instructions.md` neste diretório
2. Adicione o frontmatter com o padrão `applyTo`
3. Escreva suas instruções em Markdown natural
4. Commit e push - Copilot aplicará automaticamente!

### Template Básico

```markdown
---
applyTo: "seu/caminho/**/*.ext"
excludeAgent: "code-review"  # Opcional
---

# Título das Instruções

## Seção 1
- Regra ou guideline
- Outra regra

## Exemplos

\`\`\`typescript
// Código de exemplo
\`\`\`
```

## 📚 Documentação Oficial

- [Custom Instructions Documentation](https://docs.github.com/en/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot)
- [Path-Specific Instructions](https://docs.github.com/copilot/customizing-copilot/adding-custom-instructions-for-github-copilot#creating-path-specific-custom-instructions)

---

**Última atualização**: Novembro 2025
