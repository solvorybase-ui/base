"""Product Scout V1 orchestration: one independent AI call per variant."""
from __future__ import annotations
from dataclasses import dataclass
from .candidate_repository import load_scout_candidates
from .output_schema import validate_scout_output, ScoutOutputValidationError
from .prompt_builder import build_scout_prompt
from .result_repository import create_running_scout_result, finish_scout_success, finish_scout_failure

@dataclass(frozen=True, slots=True)
class ScoutRunStats:
    candidates: int=0
    selected: int=0
    rejected: int=0
    failed: int=0
    invalid_output: int=0

def run_product_scout(connection, *, client, prompt_template: str, prompt_version_id: str, model_name: str, model_version: str | None = None, automation_run_id: str | None = None, limit: int = 10) -> ScoutRunStats:
    candidates=load_scout_candidates(connection, limit=limit)
    selected=rejected=failed=invalid=0
    for candidate in candidates:
        result_id=create_running_scout_result(connection, product_variant_id=candidate.variant_id, prompt_version_id=prompt_version_id, model_name=model_name, model_version=model_version, automation_run_id=automation_run_id)
        prompt=build_scout_prompt(candidate, template=prompt_template)
        try:
            raw=client.evaluate(prompt=prompt, image_urls=candidate.image_urls[:3])
            output=validate_scout_output(raw, expected_variant_id=candidate.variant_id)
        except ScoutOutputValidationError as exc:
            finish_scout_failure(connection, scout_result_id=result_id, technical_status="invalid_output", error_code="invalid_output", error_summary=str(exc))
            invalid += 1
            continue
        except Exception as exc:
            finish_scout_failure(connection, scout_result_id=result_id, technical_status="failed", error_code="provider_error", error_summary=type(exc).__name__)
            failed += 1
            continue
        finish_scout_success(connection, scout_result_id=result_id, decision=output.decision, reason=output.reason)
        if output.decision=="selected": selected += 1
        else: rejected += 1
    return ScoutRunStats(len(candidates),selected,rejected,failed,invalid)
