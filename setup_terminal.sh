#!/bin/zsh
# Script de configuração para auto-ativação do ambiente ceie
# Execute: source setup_terminal.sh
# Isso adicionará uma função ao seu .zshrc para auto-ativar ceie neste diretório

PROJECT_DIR="/Users/patricia/Documents/code/python-code/CEIE/geracao_metadados/ceie_proceedings_migration"
ZSHRC_FILE="$HOME/.zshrc"

# Função para auto-ativar ceie quando entrar no diretório do projeto
AUTO_ACTIVATE_FUNCTION='
# Auto-ativação do ambiente conda ceie no diretório ceie_proceedings_migration
_auto_activate_ceie() {
    if [[ "$PWD" == "'$PROJECT_DIR'/*" ]] || [[ "$PWD" == "'$PROJECT_DIR'" ]]; then
        if [ -z "$CONDA_DEFAULT_ENV" ] || [ "$CONDA_DEFAULT_ENV" != "ceie" ]; then
            # Inicializa conda se necessário
            if [ -f "/opt/anaconda3/etc/profile.d/conda.sh" ]; then
                source "/opt/anaconda3/etc/profile.d/conda.sh"
            elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
                source "$HOME/anaconda3/etc/profile.d/conda.sh"
            fi
            
            # Ativa o ambiente ceie silenciosamente
            conda activate ceie 2>/dev/null && echo "✓ Ambiente ceie ativado automaticamente"
        fi
    elif [ "$CONDA_DEFAULT_ENV" == "ceie" ] && [[ "$PWD" != "'$PROJECT_DIR'/*" ]] && [[ "$PWD" != "'$PROJECT_DIR'" ]]; then
        # Opcional: desativa quando sair do diretório
        # conda deactivate 2>/dev/null
    fi
}

# Adiciona a função ao chpwd (mudança de diretório)
if ! [[ "$chpwd_functions" == *_auto_activate_ceie* ]]; then
    chpwd_functions=(_auto_activate_ceie $chpwd_functions)
fi
'

# Verifica se a função já existe no .zshrc
if grep -q "_auto_activate_ceie" "$ZSHRC_FILE" 2>/dev/null; then
    echo "⚠ A função de auto-ativação já existe no .zshrc"
    echo "Se desejar reconfigurar, remova manualmente a função do .zshrc"
else
    echo "" >> "$ZSHRC_FILE"
    echo "# Auto-ativação conda ceie para ceie_proceedings_migration" >> "$ZSHRC_FILE"
    echo "$AUTO_ACTIVATE_FUNCTION" >> "$ZSHRC_FILE"
    echo "✓ Função de auto-ativação adicionada ao .zshrc"
    echo "Recarregue o terminal com: source ~/.zshrc"
fi

