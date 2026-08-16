"""Read-only candidate selection for Product Scout V1."""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, Sequence, Any

class CursorLike(Protocol):
    def __enter__(self): ...
    def __exit__(self, exc_type, exc, tb): ...
    def execute(self, query: str, params: Sequence[object] | None = None) -> Any: ...
    def fetchall(self) -> list[Sequence[object]]: ...

class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...

@dataclass(frozen=True, slots=True)
class CandidateOffer:
    id: str
    shop_title: str
    product_url: str
    current_price: Decimal | None
    currency_code: str | None
    availability_status: str

@dataclass(frozen=True, slots=True)
class ScoutCandidate:
    variant_id: str
    family_name: str
    brand_name: str | None
    category: str | None
    variant_name: str
    model_name: str | None
    description: str | None
    variant_attributes: dict[str, object] = field(default_factory=dict)
    offers: tuple[CandidateOffer, ...] = ()
    image_urls: tuple[str, ...] = ()


def load_scout_candidates(connection: ConnectionLike, *, limit: int = 10) -> list[ScoutCandidate]:
    """Load active variants that do not yet have a successful Scout result."""
    if limit <= 0:
        raise ValueError("limit must be greater than zero")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pv.id, pf.name, pf.brand_name, pf.category,
                   pv.name, pv.model_name, pv.description, pv.variant_attributes,
                   o.id, o.shop_title, o.product_url, o.current_price,
                   o.currency_code, o.availability_status,
                   img.external_url
            FROM product_variants pv
            JOIN product_families pf ON pf.id = pv.product_family_id
            LEFT JOIN LATERAL (
                SELECT id, shop_title, product_url, current_price,
                       currency_code, availability_status
                FROM offers
                WHERE product_variant_id = pv.id
                  AND is_active = true
                  AND archived_at IS NULL
                ORDER BY last_seen_at DESC, id
                LIMIT 1
            ) o ON true
            LEFT JOIN LATERAL (
                SELECT external_url
                FROM product_images
                WHERE offer_id = o.id
                  AND is_active = true
                  AND archived_at IS NULL
                ORDER BY is_primary DESC, position, id
                LIMIT 3
            ) img ON true
            WHERE pv.is_active = true
              AND pv.archived_at IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM scout_results sr
                  WHERE sr.product_variant_id = pv.id
                    AND sr.technical_status = 'succeeded'
              )
            ORDER BY pv.created_at, pv.id, img.external_url
            LIMIT %s
            """,
            (limit * 3,),
        )
        rows = cursor.fetchall()

    grouped: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for row in rows:
        vid = str(row[0])
        if vid not in grouped:
            if len(order) >= limit:
                continue
            order.append(vid)
            grouped[vid] = {
                "candidate": ScoutCandidate(
                    variant_id=vid,
                    family_name=str(row[1]),
                    brand_name=None if row[2] is None else str(row[2]),
                    category=None if row[3] is None else str(row[3]),
                    variant_name=str(row[4]),
                    model_name=None if row[5] is None else str(row[5]),
                    description=None if row[6] is None else str(row[6]),
                    variant_attributes=dict(row[7] or {}),
                    offers=(), image_urls=(),
                ),
                "offer": None,
                "images": [],
            }
        item = grouped[vid]
        if row[8] is not None and item["offer"] is None:
            item["offer"] = CandidateOffer(
                id=str(row[8]), shop_title=str(row[9]), product_url=str(row[10]),
                current_price=row[11], currency_code=None if row[12] is None else str(row[12]),
                availability_status=str(row[13]),
            )
        if row[14] is not None and row[14] not in item["images"]:
            item["images"].append(str(row[14]))

    result=[]
    for vid in order:
        item=grouped[vid]; c=item["candidate"]
        offer=() if item["offer"] is None else (item["offer"],)
        result.append(ScoutCandidate(
            variant_id=c.variant_id, family_name=c.family_name, brand_name=c.brand_name,
            category=c.category, variant_name=c.variant_name, model_name=c.model_name,
            description=c.description, variant_attributes=c.variant_attributes,
            offers=offer, image_urls=tuple(item["images"][:3]),
        ))
    return result
