"""Vocabulário controlado: tags visuais, técnicas audiovisuais e ferramentas conhecidas.

Uma tag visual descreve o que um observador registrou num frame (ou par/sequência). Cada tag pode
apontar para uma categoria e/ou uma técnica. `motion=True` significa que a tag só pode ser
`observed_visual` com base `frame_sequence` ou `video_clip` (ver normalize.is_motion_tag).
"""
from __future__ import annotations

from typing import Dict, NamedTuple, Optional


class TagSpec(NamedTuple):
    category: Optional[str]
    technique: Optional[str]
    motion: bool = False
    contradicts: Optional[str] = None  # categoria que a observação contesta


VISUAL_TAGS: Dict[str, TagSpec] = {
    # interface e ferramenta
    "ui_screen_visible": TagSpec("demonstracao_ferramenta", None),
    "tool_name_visible": TagSpec("demonstracao_ferramenta", None),
    "logo_visible": TagSpec("demonstracao_ferramenta", None),
    "cursor_or_click_visible": TagSpec("demonstracao_ferramenta", None),
    "no_ui_visible": TagSpec(None, None, contradicts="demonstracao_ferramenta"),
    "step_sequence_visible": TagSpec("tutorial", None),
    "workflow_graph_on_screen": TagSpec("automacao", None),
    "informational_on_screen": TagSpec("conhecimento", None),
    "sales_offer_on_screen": TagSpec("marketing_vendas", None),
    "price_or_discount_on_screen": TagSpec("marketing_vendas", None),
    "no_offer_on_screen": TagSpec(None, None, contradicts="marketing_vendas"),
    # composição e edição (observáveis num quadro)
    "split_screen": TagSpec("edicao_audiovisual", "split_screen"),
    "b_roll_visible": TagSpec("edicao_audiovisual", "b_roll"),
    "overlay_layer": TagSpec("edicao_audiovisual", "sobreposicao"),
    "layered_composition": TagSpec("edicao_audiovisual", "sobreposicao"),
    "mask_shape": TagSpec("edicao_audiovisual", "mascara"),
    "burned_caption": TagSpec("edicao_audiovisual", "legenda_sobreposta"),
    "reframed_crop": TagSpec("edicao_audiovisual", "reenquadramento"),
    "punch_in_scale": TagSpec("edicao_audiovisual", "punch_in"),          # escala diferente entre dois quadros
    "jump_cut_pair": TagSpec("edicao_audiovisual", "jump_cut"),           # mesmo plano, descontinuidade
    "cut_pair": TagSpec("edicao_audiovisual", "corte"),
    "static_single_shot": TagSpec(None, None, contradicts="edicao_audiovisual"),
    # estética e cinematografia
    "cinematic_composition": TagSpec("cinematografia", "composicao_cinematografica"),
    "cinematic_look": TagSpec("cinematografia", "composicao_cinematografica"),
    "shallow_depth_of_field": TagSpec("cinematografia", "composicao_cinematografica"),
    "aesthetic_reference": TagSpec("referencia_estetica", None),
    "typography_styled": TagSpec("motion_design", "tipografia"),
    # movimento: exige sequência temporal
    "kinetic_typography": TagSpec("motion_design", "tipografia_cinetica", motion=True),
    "animated_caption": TagSpec("edicao_audiovisual", "legenda_animada", motion=True),
    "transition": TagSpec("edicao_audiovisual", "transicao", motion=True),
    "motion_text_in_clip": TagSpec("motion_design", "tipografia_cinetica", motion=True),
    "motion_transition_in_clip": TagSpec("motion_design", "transicao", motion=True),
    "camera_move": TagSpec("cinematografia", "movimento_de_camera", motion=True),
    "punch_in_motion": TagSpec("edicao_audiovisual", "punch_in", motion=True),
    "scroll": TagSpec("demonstracao_ferramenta", None, motion=True),
}

TECHNIQUES = {
    "split_screen": "Tela dividida: dois ou mais quadros simultâneos.",
    "b_roll": "Imagem de cobertura intercalada ao plano principal.",
    "jump_cut": "Corte dentro do mesmo plano, com descontinuidade temporal.",
    "punch_in": "Aproximação por escala (digital ou de lente) do mesmo plano.",
    "mascara": "Recorte de camada por forma ou máscara.",
    "sobreposicao": "Camadas sobrepostas (imagem, texto ou vídeo sobre vídeo).",
    "tipografia": "Texto estilizado em tela (estático).",
    "tipografia_cinetica": "Texto com movimento ou animação.",
    "legenda_sobreposta": "Legenda gravada sobre o vídeo.",
    "legenda_animada": "Legenda com animação (por palavra, escala, cor).",
    "transicao": "Passagem entre planos com efeito.",
    "reenquadramento": "Recorte ou mudança de proporção do quadro.",
    "composicao_cinematografica": "Enquadramento, luz e profundidade de campo de linguagem cinematográfica.",
    "movimento_de_camera": "Pan, tilt, dolly ou zoom real ou simulado.",
    "corte": "Mudança de plano.",
}

# Léxico de ferramentas (nome canônico -> variações em texto normalizado). Ampliável por configuração.
TOOL_LEXICON: Dict[str, tuple] = {
    "CapCut": ("capcut",),
    "Adobe After Effects": ("after effects", "aftereffects"),
    "Adobe Premiere Pro": ("premiere pro", "premiere"),
    "DaVinci Resolve": ("davinci resolve", "davinci"),
    "n8n": ("n8n",),
    "Zapier": ("zapier",),
    "Make": ("make.com",),
    "ChatGPT": ("chatgpt", "chat gpt"),
    "Claude": ("claude",),
    "Gemini": ("gemini",),
    "Midjourney": ("midjourney",),
    "ComfyUI": ("comfyui", "comfy ui"),
    "Runway": ("runway", "runwayml"),
    "Kling": ("kling",),
    "Sora": ("sora",),
    "Canva": ("canva",),
    "Notion": ("notion",),
    "ElevenLabs": ("elevenlabs", "eleven labs"),
    "HeyGen": ("heygen",),
    "Higgsfield": ("higgsfield",),
    "Magnific": ("magnific",),
    "Blender": ("blender",),
    "Figma": ("figma",),
}
