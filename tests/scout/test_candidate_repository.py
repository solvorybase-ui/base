from decimal import Decimal
import pytest
from backend.scout.candidate_repository import load_scout_candidates
class C:
 def __init__(self, rows): self.rows=rows; self.calls=[]
 def cursor(self): return X(self)
class X:
 def __init__(self,c): self.c=c
 def __enter__(self): return self
 def __exit__(self,*a): pass
 def execute(self,q,p=None): self.c.calls.append((" ".join(q.split()),p))
 def fetchall(self): return self.c.rows

def test_default_query_excludes_successful_results_and_limits_candidates():
 c=C([]); load_scout_candidates(c)
 sql,p=c.calls[0]; assert "technical_status = 'succeeded'" in sql; assert "NOT EXISTS" in sql; assert p==(None,None,None,None,30)
def test_limit_must_be_positive():
 with pytest.raises(ValueError): load_scout_candidates(C([]),limit=0)
def test_candidate_groups_images_and_one_offer():
 rows=[('v','Family','Brand','Cat','Variant','M','Desc',{'size':'L'},'o','Shop','https://x',Decimal('12.3'),'EUR','in_stock','https://i1'),('v','Family','Brand','Cat','Variant','M','Desc',{'size':'L'},'o','Shop','https://x',Decimal('12.3'),'EUR','in_stock','https://i2')]
 r=load_scout_candidates(C(rows)); assert len(r)==1; assert r[0].image_urls==('https://i1','https://i2'); assert len(r[0].offers)==1

def test_shop_filter_uses_exists_without_join_duplicates():
 c=C([]); load_scout_candidates(c,shop_id='00000000-0000-0000-0000-000000000001')
 sql,p=c.calls[0]
 assert "EXISTS ( SELECT 1 FROM offers filter_offer" in sql
 assert "filter_offer.shop_id = %s::uuid" in sql
 assert p==('00000000-0000-0000-0000-000000000001',)*2+(None,None,30)

def test_source_filter_uses_active_source_records():
 c=C([]); load_scout_candidates(c,source_id='00000000-0000-0000-0000-000000000002')
 sql,p=c.calls[0]
 assert "JOIN offer_source_records source_record" in sql
 assert "source_record.source_id = %s::uuid" in sql
 assert "source_record.is_active = true" in sql
 assert p==(None,None)+('00000000-0000-0000-0000-000000000002',)*2+(30,)

def test_shop_and_source_filters_are_combined():
 c=C([]); load_scout_candidates(c,shop_id='00000000-0000-0000-0000-000000000001',source_id='00000000-0000-0000-0000-000000000002')
 sql,p=c.calls[0]
 assert sql.count("OR EXISTS") == 2
 assert p==('00000000-0000-0000-0000-000000000001',)*2+('00000000-0000-0000-0000-000000000002',)*2+(30,)
