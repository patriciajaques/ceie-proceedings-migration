#!/bin/zsh
# Script para ativar o ambiente conda ceie
# Uso: source activate_ceie.sh

# Inicializa conda se necessário
if [ -z "$CONDA_DEFAULT_ENV" ] || [ "$CONDA_DEFAULT_ENV" != "ceie" ]; then
    # Tenta encontrar o conda
    if [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/anaconda3/etc/profile.d/conda.sh"
    elif [ -f "/opt/anaconda3/etc/profile.d/conda.sh" ]; then
        source "/opt/anaconda3/etc/profile.d/conda.sh"
    fi
    
    # Ativa o ambiente ceie
    conda activate ceie 2>/dev/null || {
        echo "Erro: Não foi possível ativar o ambiente conda 'ceie'"
        echo "Verifique se o conda está instalado e o ambiente 'ceie' existe"
        return 1
    }
    
    echo "✓ Ambiente conda 'ceie' ativado"
    echo "Python: $(which python)"
    echo "Versão: $(python --version)"
fi

