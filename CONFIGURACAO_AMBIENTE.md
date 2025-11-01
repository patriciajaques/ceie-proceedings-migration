# Configuração do Ambiente Conda CEIE

Este projeto está configurado para usar automaticamente o ambiente conda `ceie`.

## Configurações Aplicadas

### 1. Cursor/VSCode

Os arquivos de configuração foram criados em:

- `.vscode/settings.json` - Configurações do VSCode/Cursor
- `.cursor/settings.json` - Configurações específicas do Cursor

O interpretador Python está configurado para: `/opt/anaconda3/envs/ceie/bin/python`

### 2. Terminal (Auto-ativação)

Foi adicionada uma função ao seu `.zshrc` que automaticamente ativa o ambiente `ceie` quando você entra no diretório deste projeto.

**Para ativar a configuração agora**, execute no terminal:

```bash
source ~/.zshrc
```

A partir de agora, sempre que você entrar neste diretório, o ambiente `ceie` será ativado automaticamente.

### 3. Scripts Auxiliares

- `activate_ceie.sh` - Script manual para ativar o ambiente (caso necessário)
  - Uso: `source activate_ceie.sh`

## Como Usar

### No Cursor/VSCode

1. Abra o projeto no Cursor
2. O interpretador Python será automaticamente configurado para usar `ceie`
3. Você pode verificar isso no canto inferior direito do Cursor, onde deve aparecer o Python do ambiente `ceie`

### No Terminal

**Método Automático (Recomendado):**

- Simplesmente navegue até o diretório do projeto
- O ambiente será ativado automaticamente
- Você verá `(ceie)` no início do prompt

**Método Manual:**

```bash
conda activate ceie
# ou
source activate_ceie.sh
```

## Verificação

Para verificar se o ambiente está correto:

```bash
which python
# Deve mostrar: /opt/anaconda3/envs/ceie/bin/python

python --version
# Deve mostrar a versão do Python do ambiente ceie
```

## Remoção do Ambiente venv

O ambiente virtual `venv` foi removido, pois não é mais necessário. O projeto agora usa exclusivamente o ambiente conda `ceie`.

## Solução de Problemas

Se o ambiente não for ativado automaticamente:

1. Recarregue o shell: `source ~/.zshrc`
2. Verifique se o conda está instalado: `conda --version`
3. Verifique se o ambiente existe: `conda env list`
4. Ative manualmente: `conda activate ceie`
