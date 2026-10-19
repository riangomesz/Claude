"""JSON Schemas (draft 2020-12, subconjunto) dos contratos públicos, gerados das constantes do código,
e um validador mínimo só com a stdlib (sem o pacote `jsonschema`).

Os schemas cobrem ESTRUTURA (tipos, enums, chaves obrigatórias, contrato fechado). As regras semânticas
(fonte permitida por status, tempos dentro da duração, nível de técnica × base visual, etc.) continuam em
`ii_mm.contract.validate_document` e `ii_mm.n8n_contract.validate_mission`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _num():
    return {"type": "number"}


def schemas() -> Dict[str, Dict[str, Any]]:
    from ii_mm import SCHEMA_VERSION
    from ii_mm.adapters import ATTRIBUTE_SPEC, OBSERVATION_KINDS
    from ii_mm.contract import (EVIDENCE_STATUSES, KNOWN_TOP_LEVEL, PLATFORMS, REVIEW_STATES, SOURCE_TYPES, TECHNIQUE_LEVELS,
                                TOOL_STATUSES, VISUAL_BASES)
    from ii_mm.evidence_rules import CATEGORIES, SUPPORT_LEVELS
    from ii_mm.n8n_contract import ARTIFACT_KINDS, ERROR_CODES, MAX_ARTIFACTS, MISSION_SCHEMA, RESULT_SCHEMA
    from ii_mm.narrative import BLOCK_STATES, BLOCK_TYPES
    from ii_mm.pipeline import STAGES

    nullable_num = {"type": ["number", "null"]}
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    evidence = {"type": "object", "required": ["evidence_id", "status", "source_type", "claim", "provenance"],
                "properties": {"evidence_id": {"type": "string", "minLength": 1}, "status": {"enum": list(EVIDENCE_STATUSES)},
                               "source_type": {"enum": list(SOURCE_TYPES)}, "claim": {"type": "string", "minLength": 1},
                               "t_start_s": nullable_num, "t_end_s": nullable_num, "ref": {"type": ["string", "null"]},
                               "tag": {"type": ["string", "null"]}, "basis": {"enum": list(VISUAL_BASES) + [None]},
                               "provenance": {"type": "object", "required": ["source"]}, "extra": {"type": "object"}}}
    reference_analysis = {
        "$schema": DRAFT, "$id": f"{SCHEMA_VERSION}.schema.json", "title": SCHEMA_VERSION, "type": "object",
        "required": ["schema_version", "reference", "video"],
        "properties": {k: {} for k in sorted(KNOWN_TOP_LEVEL)} | {
            "schema_version": {"const": SCHEMA_VERSION},
            "reference": {"type": "object", "required": ["reference_id", "platform"],
                          "properties": {"reference_id": {"type": "string", "minLength": 1}, "platform": {"enum": list(PLATFORMS)},
                                         "origin_url": {"type": ["string", "null"]}, "author_handle": {"type": ["string", "null"]}}},
            "video": {"type": "object", "required": ["video_id", "duration_s"],
                      "properties": {"video_id": {"type": "string", "minLength": 1}, "duration_s": {"type": "number", "exclusiveMinimum": 0},
                                     "content_sha256": {"anyOf": [sha, {"type": "null"}]}}},
            "transcript": {"type": "array", "items": {"type": "object", "required": ["segment_id", "t_start_s", "t_end_s", "text"]}},
            "frames": {"type": "array", "items": {"type": "object", "required": ["frame_id", "t_s", "sha256"], "properties": {"sha256": sha}}},
            "evidence": {"type": "array", "items": evidence},
            "categories": {"type": "array", "items": {"type": "object", "required": ["category", "support", "evidence_ids"],
                                                      "properties": {"category": {"enum": list(CATEGORIES)}, "support": {"enum": list(SUPPORT_LEVELS)},
                                                                     "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                                                     "review_state": {"enum": list(REVIEW_STATES)}}}},
            "tools": {"type": "array", "items": {"type": "object", "required": ["name", "status"],
                                                 "properties": {"status": {"enum": list(TOOL_STATUSES)}}}},
            "techniques": {"type": "array", "items": {"type": "object", "required": ["technique", "level"],
                                                      "properties": {"level": {"enum": list(TECHNIQUE_LEVELS)}}}},
            "narrative_blocks": {"type": "array", "items": {"type": "object", "required": ["block_id", "type", "status"],
                                                            "properties": {"type": {"enum": list(BLOCK_TYPES)}, "status": {"enum": list(BLOCK_STATES)}}}},
        },
        "patternProperties": {"^x_": {}}, "additionalProperties": False,
    }
    attr_props = {k: ({"type": "string", "maxLength": 20} if v is None else
                      {"type": "integer", "minimum": min(v), "maximum": max(v)} if isinstance(v, range) else {"enum": sorted(v)})
                  for k, v in ATTRIBUTE_SPEC.items()}
    visual_observation = {
        "$schema": DRAFT, "$id": "ii.visual_observation.v1.schema.json", "title": "ii.visual_observation.v1", "type": "object",
        "required": ["observations"], "properties": {"observations": {"type": "array", "items": {
            "type": "object", "required": ["frame_refs", "t_s", "tag", "text"],
            "properties": {"frame_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}}, "t_s": _num(),
                           "tag": {"type": "string", "minLength": 1}, "text": {"type": "string", "minLength": 1},
                           "kind": {"enum": list(OBSERVATION_KINDS)}, "basis": {"enum": list(VISUAL_BASES)},
                           "attributes": {"type": "object", "properties": attr_props, "additionalProperties": False}}}}},
    }
    mission = {
        "$schema": DRAFT, "$id": f"{MISSION_SCHEMA}.schema.json", "title": MISSION_SCHEMA, "type": "object", "additionalProperties": False,
        "required": ["schema_version", "mission_id", "reference", "requested_stages", "requested_by", "created_at"],
        "properties": {"schema_version": {"const": MISSION_SCHEMA}, "mission_id": {"type": "string", "pattern": "^ms_[0-9a-f]{24}$"},
                       "reference": {"type": "object", "additionalProperties": False,
                                     "properties": {"platform": {"enum": list(PLATFORMS)}, "url": {"type": "string"}, "video_id": {"type": "string"}}},
                       "requested_stages": {"type": "array", "minItems": 1, "items": {"enum": list(STAGES)}},
                       "artifacts": {"type": "array", "maxItems": MAX_ARTIFACTS, "items": {
                           "type": "object", "additionalProperties": False, "required": ["kind", "sha256", "uri"],
                           "properties": {"kind": {"enum": list(ARTIFACT_KINDS)}, "sha256": sha,
                                          "uri": {"type": "string", "minLength": 1, "maxLength": 512, "pattern": r"^[^:\\/][^:]*$"},
                                          "bytes": {"type": "integer", "minimum": 0}}}},
                       "budget": {"type": "object", "additionalProperties": False,
                                  "properties": {"allow_paid_models": {"type": "boolean"}, "max_usd": _num(), "approved_by": {"type": "string"}}},
                       "requested_by": {"type": "string", "minLength": 1, "maxLength": 2048},
                       "created_at": {"type": "string", "minLength": 1, "maxLength": 2048}},
    }
    result = {
        "$schema": DRAFT, "$id": f"{RESULT_SCHEMA}.schema.json", "title": RESULT_SCHEMA, "type": "object",
        "required": ["schema_version", "mission_id", "state", "error", "next_action"],
        "properties": {"schema_version": {"const": RESULT_SCHEMA}, "mission_id": {"type": "string"},
                       "state": {"enum": list(STAGES) + ["failed", "rejected", "busy"]},
                       "error": {"anyOf": [{"type": "null"}, {"type": "object", "required": ["code", "retryable"],
                                                              "properties": {"code": {"enum": sorted(ERROR_CODES)}, "retryable": {"type": "boolean"}}}]},
                       "next_action": {"enum": ["retry", "human", "provide_evidence", "fix_message", "await_review", "retry_later", "none"]}},
    }
    return {f"{SCHEMA_VERSION}.schema.json": reference_analysis, "ii.visual_observation.v1.schema.json": visual_observation,
            f"{MISSION_SCHEMA}.schema.json": mission, f"{RESULT_SCHEMA}.schema.json": result}


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is_type(value: Any, t: str) -> bool:
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[t])


def validate(instance: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """Validador do subconjunto usado acima: type, const, enum, required, properties, patternProperties,
    additionalProperties (bool), items, min/maxItems, min/maxLength, pattern, minimum, maximum, exclusiveMinimum, anyOf."""
    errs: List[str] = []
    if "anyOf" in schema:
        if all(validate(instance, s, path) for s in schema["anyOf"]):
            errs.append(f"{path}: não corresponde a nenhuma alternativa")
        return errs
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is_type(instance, x) for x in types):
            return [f"{path}: tipo esperado {types}"]
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{path}: deve ser {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: valor fora do enum: {instance!r}")
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0) or len(instance) > schema.get("maxLength", 1 << 30):
            errs.append(f"{path}: tamanho inválido")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errs.append(f"{path}: não casa com {schema['pattern']}")
    if _is_type(instance, "number"):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{path}: abaixo do mínimo")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{path}: acima do máximo")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errs.append(f"{path}: deve ser > {schema['exclusiveMinimum']}")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0) or len(instance) > schema.get("maxItems", 1 << 30):
            errs.append(f"{path}: quantidade de itens inválida")
        if "items" in schema:
            for i, v in enumerate(instance):
                errs += validate(v, schema["items"], f"{path}[{i}]")
    if isinstance(instance, dict):
        for k in schema.get("required", []):
            if k not in instance:
                errs.append(f"{path}: chave obrigatória ausente: {k}")
        props, patterns = schema.get("properties", {}), schema.get("patternProperties", {})
        for k, v in instance.items():
            if k in props:
                errs += validate(v, props[k], f"{path}.{k}")
            elif any(re.search(pat, k) for pat in patterns):
                continue
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: chave não permitida: {k}")
    return errs
