import json
from pathlib import Path
from typing import Tuple, List, Dict
import difflib

from src.config.config_loader import ConfigLoader
from src.utils.text_processor import TextProcessor


def _extract_text_with_error(instruction: str) -> str:
    """
    Extrai o bloco de texto após o marcador 'TEXT WITH ERROR:' na instrução.
    """
    marker = "TEXT WITH ERROR:"
    idx = instruction.find(marker)
    if idx == -1:
        return instruction.strip()
    return instruction[idx + len(marker) :].strip()


def _normalize_with_our_algorithm(text: str, processor: TextProcessor) -> str:
    """
    Aplica apenas o algoritmo local de correção de encoding
    (apply_known_encoding_fixes + basic_cleaning), sem chamar LLM.
    """
    fixed = processor.apply_known_encoding_fixes(text)
    cleaned = processor.basic_cleaning(fixed)
    return cleaned


def _summarize_differences(
    a: str,
    b: str,
    max_snippets: int,
    window: int,
) -> List[Dict[str, str]]:
    """
    Gera pequenos trechos onde as strings diferem, usando difflib para localizar
    as diferenças e retornando janelas de contexto em torno dessas regiões.

    A parte diferente em cada string é destacada entre colchetes [...],
    com um pouco de contexto antes e depois.
    """
    snippets: List[Dict[str, str]] = []
    matcher = difflib.SequenceMatcher(a=a, b=b)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if max_snippets is not None and len(snippets) >= max_snippets:
            break

        # Define uma janela em torno da diferença
        start_a = max(i1 - window, 0)
        end_a = min(i2 + window, len(a))
        start_b = max(j1 - window, 0)
        end_b = min(j2 + window, len(b))

        # Destaca o trecho diferente com colchetes
        local_ctx = a[start_a:i1] + "[" + a[i1:i2] + "]" + a[i2:end_a]
        llm_ctx = b[start_b:j1] + "[" + b[j1:j2] + "]" + b[j2:end_b]

        snippets.append(
            {
                "local": local_ctx,
                "llm": llm_ctx,
            }
        )

    return snippets


def main(
    max_samples: int = 50,
    max_diffs: int | None = 15,
    max_snippets_per_diff: int | None = 5,
    diff_window: int = 20,
) -> None:
    """
    Varre o arquivo ai_calls.log.jsonl e, para chamadas com step == "text_processing",
    compara a saída da LLM com a saída do nosso algoritmo de correção.

    Relata:
    - quantos casos batem exatamente
    - quantos diferem
    - alguns exemplos de divergência para inspeção manual.
    """
    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "config" / "config.json"
    config_loader = ConfigLoader(str(config_path))

    output_dir = config_loader.get_config_value("output_dir")
    year = config_loader.get_config_value("year")
    logs_dir = Path(output_dir) / str(year) / "logs"
    log_path = logs_dir / "ai_calls.log.jsonl"

    if not log_path.exists():
        raise FileNotFoundError(f"Log de chamadas à IA não encontrado: {log_path}")

    processor = TextProcessor(ai_client=None)

    total = 0
    exact_matches = 0
    would_call_llm = 0
    diffs = []

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            if max_samples > 0 and total >= max_samples:
                break
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("step") != "text_processing":
                continue

            instruction = entry.get("instruction") or ""
            response = (entry.get("response") or "").strip()
            if not instruction or not response:
                continue

            original_text = _extract_text_with_error(instruction)
            local_fixed = _normalize_with_our_algorithm(original_text, processor)
            llm_fixed = processor.basic_cleaning(response)

            total += 1

            # Simula a lógica atual do TextProcessor: depois das correções
            # determinísticas, ainda há padrões de encoding? Se sim, LLM seria chamada.
            if processor.detect_encoding_errors(local_fixed):
                would_call_llm += 1

            if local_fixed == llm_fixed:
                exact_matches += 1
            else:
                if max_diffs is None or len(diffs) < max_diffs:
                    diffs.append(
                        {
                            "original": original_text,
                            "local_fixed": local_fixed,
                            "llm_fixed": llm_fixed,
                            "snippets": _summarize_differences(
                                local_fixed,
                                llm_fixed,
                                max_snippets=max_snippets_per_diff,
                                window=diff_window,
                            ),
                        }
                    )

    print(f"Total de amostras analisadas (text_processing): {total}")
    print(f"Casos em que nosso algoritmo == LLM: {exact_matches}")
    if total:
        print(f"Proporção de acerto exato: {exact_matches / total:.2%}")
        print(f"Casos em que AINDA chamaríamos LLM (detect_encoding_errors=True): {would_call_llm}")
        print(f"Proporção de textos que ainda iriam para LLM: {would_call_llm / total:.2%}")

    if diffs:
        print("\nExemplos de divergências (com trechos onde diferem):\n")
        for i, diff in enumerate(diffs, start=1):
            print(f"--- Divergência {i} ---")
            print("Original (trecho inicial):")
            print(diff["original"][:300])
            print("\nTrechos com diferença (Local vs LLM):")
            for j, snip in enumerate(diff["snippets"], start=1):
                print(f"\n  * Trecho {j} - Local:")
                print(f"    {snip['local']}")
                print("    LLM:")
                print(f"    {snip['llm']}")
            print()


if __name__ == "__main__":
    import os
    # Limpa a tela (funciona em Unix e Windows)
    os.system("cls" if os.name == "nt" else "clear")

    # Parâmetros padrão de execução:
    # - max_samples: quantas entradas step=="text_processing" analisar
    # - max_diffs: quantos artigos com divergência mostrar (None = todos)
    # - max_snippets_per_diff: quantos trechos diferentes por artigo (None = todos)
    # - diff_window: tamanho da janela de contexto em torno da diferença
    main(
        max_samples=50,
        max_diffs=None,
        max_snippets_per_diff=None,
        diff_window=20,
    )