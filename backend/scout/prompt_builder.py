"""Build one Product Scout prompt per candidate."""
from __future__ import annotations
import json
from pathlib import Path
from .candidate_repository import ScoutCandidate

DEFAULT_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "product_scout_v1.md"

def load_prompt_template(path: Path = DEFAULT_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")

def build_scout_prompt(candidate: ScoutCandidate, *, template: str) -> str:
    payload={
        "variant_id": candidate.variant_id,
        "family_name": candidate.family_name,
        "brand_name": candidate.brand_name,
        "category": candidate.category,
        "variant_name": candidate.variant_name,
        "model_name": candidate.model_name,
        "description": candidate.description,
        "variant_attributes": candidate.variant_attributes,
        "offers": [{"shop_title":o.shop_title,"product_url":o.product_url,"current_price":str(o.current_price) if o.current_price is not None else None,"currency_code":o.currency_code,"availability_status":o.availability_status} for o in candidate.offers],
        "image_urls": list(candidate.image_urls),
    }
    return template.rstrip()+"\n\n## Candidate data\n```json\n"+json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+"\n```\n"
