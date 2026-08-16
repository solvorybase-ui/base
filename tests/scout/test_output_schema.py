import pytest
from backend.scout.output_schema import validate_scout_output, ScoutOutputValidationError
BASE={'variant_id':'v1','decision':'selected','reason':'useful','usefulness':'high','functional_distinction':'clear','functional_distinction_summary':'feature'}
def test_valid_output(): assert validate_scout_output(BASE,expected_variant_id='v1').decision=='selected'
@pytest.mark.parametrize('field,value',[('decision','maybe'),('usefulness','great'),('functional_distinction','strong'),('variant_id','other'),('reason','')])
def test_invalid_values(field,value):
 d=dict(BASE); d[field]=value
 with pytest.raises(ScoutOutputValidationError): validate_scout_output(d,expected_variant_id='v1')
def test_extra_fields_rejected():
 d=dict(BASE); d['hit']='yes'
 with pytest.raises(ScoutOutputValidationError): validate_scout_output(d,expected_variant_id='v1')
