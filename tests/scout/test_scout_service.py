from backend.scout.candidate_repository import ScoutCandidate
import backend.scout.scout_service as svc
class Client:
 def __init__(self,items): self.items=list(items); self.calls=[]
 def evaluate(self,*,prompt,image_urls=()): self.calls.append((prompt, tuple(image_urls))); x=self.items.pop(0); 
 def evaluate(self,*,prompt,image_urls=()):
  self.calls.append((prompt, tuple(image_urls))); x=self.items.pop(0)
  if isinstance(x,Exception): raise x
  return x
class Conn: pass
VALID=lambda d='selected': {'decision':d,'reason':'reason','usefulness':'high','functional_distinction':'clear','functional_distinction_summary':'summary'}
def setup(monkeypatch, candidates):
 monkeypatch.setattr(svc,'load_scout_candidates',lambda connection,limit=10,shop_id=None,source_id=None:candidates)
 ids=iter([f'r{i}' for i in range(99)]); events=[]
 monkeypatch.setattr(svc,'create_running_scout_result',lambda connection,**kw:(events.append(('start',kw)) or next(ids)))
 monkeypatch.setattr(svc,'finish_scout_success',lambda connection,**kw:events.append(('success',kw)))
 monkeypatch.setattr(svc,'finish_scout_failure',lambda connection,**kw:events.append(('failure',kw)))
 return events
def test_one_call_per_variant_and_selected_rejected(monkeypatch):
 cs=[ScoutCandidate('v1','f',None,None,'a',None,None),ScoutCandidate('v2','f',None,None,'b',None,None)]
 ev=setup(monkeypatch,cs); client=Client([VALID(),VALID('rejected')])
 s=svc.run_product_scout(Conn(),client=client,prompt_template='P',prompt_version_id='pv',model_name='model')
 assert len(client.calls)==2; assert (s.selected,s.rejected)==(1,1); assert len([e for e in ev if e[0]=='success'])==2
def test_invalid_output_never_rejected(monkeypatch):
 ev=setup(monkeypatch,[ScoutCandidate('v1','f',None,None,'a',None,None)]); c=Client([{'decision':'rejected'}])
 s=svc.run_product_scout(Conn(),client=c,prompt_template='P',prompt_version_id='pv',model_name='model')
 assert s.invalid_output==1 and s.rejected==0; assert ev[-1][0]=='failure'; assert ev[-1][1]['technical_status']=='invalid_output'
def test_provider_failure_never_rejected_and_next_candidate_runs(monkeypatch):
 ev=setup(monkeypatch,[ScoutCandidate('v1','f',None,None,'a',None,None),ScoutCandidate('v2','f',None,None,'b',None,None)])
 c=Client([RuntimeError('secret connection text'),VALID()]); s=svc.run_product_scout(Conn(),client=c,prompt_template='P',prompt_version_id='pv',model_name='m')
 assert s.failed==1 and s.selected==1 and s.rejected==0; assert len(c.calls)==2; assert ev[1][1]['error_summary']=='RuntimeError'
def test_limit_default_is_ten(monkeypatch):
 seen={}
 def fake_load(connection,limit=10,shop_id=None,source_id=None):
  seen['limit']=limit
  return []
 monkeypatch.setattr(svc,'load_scout_candidates',fake_load)
 svc.run_product_scout(Conn(),client=Client([]),prompt_template='P',prompt_version_id='pv',model_name='m'); assert seen['limit']==10

def test_candidate_filters_are_forwarded(monkeypatch):
 seen={}
 def fake_load(connection,**kwargs):
  seen.update(kwargs); return []
 monkeypatch.setattr(svc,'load_scout_candidates',fake_load)
 svc.run_product_scout(Conn(),client=Client([]),prompt_template='P',prompt_version_id='pv',model_name='m',shop_id='shop',source_id='source')
 assert seen == {'limit':10,'shop_id':'shop','source_id':'source'}

def test_candidate_images_are_forwarded_to_client_with_maximum_three(monkeypatch):
 candidate=ScoutCandidate('v1','f',None,None,'a',None,None,image_urls=('u1','u2','u3','u4'))
 setup(monkeypatch,[candidate]); client=Client([VALID()])
 svc.run_product_scout(Conn(),client=client,prompt_template='P',prompt_version_id='pv',model_name='m')
 assert client.calls[0][1] == ('u1','u2','u3')

def test_results_for_consecutive_candidates_use_server_side_candidate_identity(monkeypatch):
 candidates=[ScoutCandidate('v1','f',None,None,'a',None,None),ScoutCandidate('v2','f',None,None,'b',None,None)]
 events=setup(monkeypatch,candidates)
 stats=svc.run_product_scout(Conn(),client=Client([VALID(),VALID('rejected')]),prompt_template='P',prompt_version_id='pv',model_name='m')
 starts=[event[1] for event in events if event[0]=='start']
 successes=[event[1] for event in events if event[0]=='success']
 assert [start['product_variant_id'] for start in starts] == ['v1','v2']
 assert [success['scout_result_id'] for success in successes] == ['r0','r1']
 assert (stats.selected,stats.rejected)==(1,1)
