import pytest
from backend.scout.output_schema import validate_scout_output, ScoutOutputValidationError
BASE={'decision':'selected','reason':'useful','usefulness':'high','functional_distinction':'clear','functional_distinction_summary':'feature'}
def test_valid_output(): assert validate_scout_output(BASE).decision=='selected'
@pytest.mark.parametrize('field,value',[('decision','maybe'),('usefulness','great'),('functional_distinction','strong'),('reason','')])
def test_invalid_values(field,value):
 d=dict(BASE); d[field]=value
 with pytest.raises(ScoutOutputValidationError): validate_scout_output(d)
def test_extra_fields_rejected():
 d=dict(BASE); d['hit']='yes'
 with pytest.raises(ScoutOutputValidationError): validate_scout_output(d)

def test_model_output_must_not_contain_variant_id():
 d=dict(BASE); d['variant_id']='v1'
 with pytest.raises(ScoutOutputValidationError): validate_scout_output(d)
