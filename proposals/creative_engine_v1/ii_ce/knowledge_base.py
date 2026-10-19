"""Conhecimento GERAL de produção audiovisual (não observado em nenhum vídeo). Tudo aqui é rótulo de SUGESTÃO:
serve para propor hipóteses de reprodução, nunca para afirmar como um vídeo específico foi feito.
Sem parâmetros numéricos de edição: valores exatos exigem teste ou informação do autor."""
from typing import Any, Dict

PRODUCTION: Dict[str, Dict[str, Any]] = {
    "legenda_sobreposta": {"hypothesis": "texto sobreposto à imagem (legenda gravada ou camada de texto)",
        "operations": ["definir o texto e a divisão em linhas", "criar camada de texto", "posicionar dentro da área segura vertical", "sincronizar com a fala"],
        "tools": ["editor de vídeo com camada de texto"], "missing": ["fonte, tamanho e contorno", "se é gerada automaticamente ou manual"],
        "errors": ["texto sob a interface da plataforma", "contraste baixo sobre fundo claro"], "quality": ["legível em tela de celular sem zoom"]},
    "legenda_animada": {"hypothesis": "legenda com animação de entrada por palavra ou bloco",
        "operations": ["gerar a legenda com tempos por palavra", "aplicar preset de animação de texto", "ajustar duração da animação"],
        "tools": ["editor com legendas animadas ou composição de texto"], "missing": ["tipo de animação", "duração por palavra"],
        "errors": ["animação mais lenta que a fala", "palavras que saem antes de serem lidas"], "quality": ["leitura confortável no ritmo da fala"]},
    "tipografia_cinetica": {"hypothesis": "texto animado como elemento principal do quadro",
        "operations": ["roteirizar as palavras-chave", "animar posição/escala/opacidade por palavra", "sincronizar com áudio"],
        "tools": ["software de composição ou editor com keyframes"], "missing": ["curvas de movimento", "duração"],
        "errors": ["excesso de movimento simultâneo", "perda de legibilidade"], "quality": ["hierarquia clara entre palavras"]},
    "tipografia": {"hypothesis": "texto estilizado como parte da identidade do vídeo",
        "operations": ["escolher família tipográfica", "definir hierarquia", "aplicar nos títulos"], "tools": ["editor de vídeo ou design"],
        "missing": ["família tipográfica"], "errors": ["mistura de fontes sem critério"], "quality": ["consistência entre cartelas"]},
    "punch_in": {"hypothesis": "aumento de escala (zoom digital) para dar ênfase",
        "operations": ["duplicar o trecho ou aplicar keyframe de escala", "recortar o enquadramento", "alinhar ao ponto de ênfase da fala"],
        "tools": ["qualquer editor com escala/keyframe"], "missing": ["percentual de escala", "se foi corte seco ou animado"],
        "errors": ["perda de nitidez em fonte de baixa resolução", "reenquadramento que corta o rosto"], "quality": ["nitidez preservada após o zoom"]},
    "jump_cut": {"hypothesis": "remoção de pausas com cortes secos no mesmo plano", "operations": ["marcar pausas e hesitações", "cortar", "revisar continuidade do áudio"],
        "tools": ["editor de vídeo"], "missing": ["critério de corte"], "errors": ["cortes que quebram a respiração da fala"], "quality": ["áudio contínuo sem estalos"]},
    "corte": {"hypothesis": "troca de plano por corte direto", "operations": ["selecionar planos", "cortar em pontos de ação ou fala"], "tools": ["editor de vídeo"],
        "missing": ["lógica de montagem"], "errors": ["corte sem motivação visual"], "quality": ["ritmo coerente com a narrativa"]},
    "split_screen": {"hypothesis": "dois ou mais elementos lado a lado no quadro", "operations": ["definir a grade", "posicionar camadas", "alinhar duração e áudio"],
        "tools": ["editor com camadas"], "missing": ["proporção da divisão"], "errors": ["áudio de duas fontes competindo"], "quality": ["foco claro em um dos lados"]},
    "b_roll": {"hypothesis": "imagens de apoio sobre a narração", "operations": ["listar o que ilustrar", "captar ou selecionar imagens", "cobrir a fala"],
        "tools": ["editor de vídeo"], "missing": ["origem das imagens"], "errors": ["imagem que contradiz a fala"], "quality": ["relação clara com a mensagem"]},
    "mascara": {"hypothesis": "recorte/máscara para isolar ou revelar elemento", "operations": ["criar máscara", "rastrear se houver movimento", "compor camadas"],
        "tools": ["editor com máscaras ou composição"], "missing": ["se a máscara é rastreada"], "errors": ["bordas serrilhadas", "máscara que escorrega"], "quality": ["bordas limpas em movimento"]},
    "sobreposicao": {"hypothesis": "camadas visuais empilhadas (overlay)", "operations": ["importar camada", "ajustar modo de mesclagem/opacidade", "posicionar"],
        "tools": ["editor com múltiplas trilhas"], "missing": ["modo de mesclagem"], "errors": ["sobreposição cobrindo informação"], "quality": ["camadas sem ruído visual"]},
    "transicao": {"hypothesis": "transição entre planos (corte estilizado, wipe, zoom ou efeito)", "operations": ["alinhar saída e entrada", "aplicar efeito de transição", "ajustar duração"],
        "tools": ["editor com transições"], "missing": ["tipo e duração"], "errors": ["transição que atrasa o ritmo"], "quality": ["continuidade de movimento entre planos"]},
    "reenquadramento": {"hypothesis": "recorte para formato vertical ou novo foco", "operations": ["ajustar a sequência para 9:16", "reposicionar o assunto"],
        "tools": ["editor de vídeo"], "missing": ["resolução de origem"], "errors": ["assunto cortado"], "quality": ["assunto na área segura"]},
    "composicao_cinematografica": {"hypothesis": "enquadramento e iluminação deliberados (profundidade, contraste, paleta)", "operations": ["definir enquadramento", "controlar luz", "etalonagem de cor"],
        "tools": ["câmera ou geração de imagem/vídeo por IA", "software de cor"], "missing": ["lente, luz, paleta exata"], "errors": ["iluminação plana", "paleta inconsistente entre planos"], "quality": ["coerência de luz e cor entre planos"]},
    "movimento_de_camera": {"hypothesis": "movimento de câmera (real ou simulado)", "operations": ["definir o movimento", "executar com estabilização ou simular na pós"],
        "tools": ["câmera/gimbal ou geração de vídeo por IA"], "missing": ["tipo de movimento, velocidade"], "errors": ["tremor", "movimento sem motivação narrativa"], "quality": ["movimento suave e motivado"]},
}
DEFAULT_PRODUCTION = {"hypothesis": "técnica sem entrada na base de conhecimento", "operations": ["pesquisar a técnica", "testar em um trecho curto"], "tools": [],
                      "missing": ["todos os parâmetros"], "errors": [], "quality": ["comparar com a referência lado a lado"]}

# Princípio criativo (derivado do que foi observado/dito) -> mecanismo reutilizável SEM copiar o vídeo
PRINCIPLES = {
    "gancho_verbal": "abrir com uma frase direta que promete um resultado nos primeiros segundos",
    "texto_na_tela": "reforçar a mensagem com texto legível sincronizado à fala",
    "demonstracao_de_processo": "mostrar o processo na tela, passo a passo, em vez de só descrevê-lo",
    "enfase_por_escala": "marcar o ponto mais importante com mudança de escala ou enquadramento",
    "ritmo_de_corte": "manter o ritmo com cortes frequentes e sem pausas mortas",
    "prova_visual": "mostrar o resultado final antes ou durante a explicação",
    "composicao_cuidada": "tratar luz, composição e paleta como parte da mensagem",
    "chamada_comercial": "fechar com uma chamada clara e específica",
}
