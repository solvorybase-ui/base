"""Strict validation for Product Scout V1 structured output."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Any

class ScoutOutputValidationError(ValueError): pass

@dataclass(frozen=True, slots=True)
class ScoutOutput:
    variant_id: str
    decision: str
    reason: str
    usefulness: str
    functional_distinction: str
    functional_distinction_summary: str

_ALLOWED_KEYS={"variant_id","decision","reason","usefulness","functional_distinction","functional_distinction_summary"}

def validate_scout_output(data: Mapping[str, Any], *, expected_variant_id: str) -> ScoutOutput:
    if set(data) != _ALLOWED_KEYS:
        missing=sorted(_ALLOWED_KEYS-set(data)); extra=sorted(set(data)-_ALLOWED_KEYS)
        raise ScoutOutputValidationError(f"invalid output fields; missing={missing}, extra={extra}")
    values={k:data[k] for k in _ALLOWED_KEYS}
    if any(not isinstance(v,str) or not v.strip() for v in values.values()):
        raise ScoutOutputValidationError("all output fields must be non-empty strings")
    variant_id=values["variant_id"].strip()
    if variant_id != expected_variant_id:
        raise ScoutOutputValidationError("variant_id does not match requested candidate")
    decision=values["decision"].strip()
    if decision not in {"selected","rejected"}:
        raise ScoutOutputValidationError("decision must be selected or rejected")
    usefulness=values["usefulness"].strip()
    if usefulness not in {"low","medium","high"}:
        raise ScoutOutputValidationError("usefulness must be low, medium, or high")
    distinction=values["functional_distinction"].strip()
    if distinction not in {"none","weak","clear"}:
        raise ScoutOutputValidationError("functional_distinction must be none, weak, or clear")
    return ScoutOutput(variant_id,decision,values["reason"].strip(),usefulness,distinction,values["functional_distinction_summary"].strip())
