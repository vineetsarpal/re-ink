"""Review keeps real workflow evidence and refuses implicit mandatory values."""
import pytest
from pydantic import ValidationError
from app.schemas.document import ExtractionResult, ReviewData

def test_review_shape_preserves_absent_evidence_and_missing_facts():
    result = ExtractionResult(contract_data={'contract_name': 'Synthetic treaty'}, parties_data=[{'name': 'Synthetic insurer'}])
    assert result.field_sources is None
    assert 'currency' not in result.contract_data
    assert 'role' not in result.parties_data[0]

def test_review_shape_retains_normalized_evidence():
    result = ExtractionResult(contract_data={'contract_name': 'Synthetic treaty'}, parties_data=[{'name': 'Synthetic insurer'}], field_sources={
        'contract': {'contract_name': {'source_text': 'Synthetic treaty', 'page_number': 1,
            'bbox': {'left': .1, 'top': .2, 'right': .8, 'bottom': .3}}}, 'parties': [{}]})
    assert result.field_sources.contract['contract_name'].page_number == 1
    assert result.field_sources.parties == [{}]

def _review():
    return {'contract': {'contract_number': 'SYN-1', 'contract_name': 'Synthetic treaty',
        'effective_date': '2026-01-01', 'expiration_date': '2027-01-01', 'currency': 'CAD'},
        'parties': [{'action': 'create_new', 'role': 'cedant', 'party_data': {'name': 'Synthetic insurer'}}]}

@pytest.mark.parametrize('field', ['contract_number', 'contract_name', 'currency', 'effective_date', 'expiration_date'])
def test_review_requires_explicit_values(field):
    data = _review()
    del data['contract'][field]
    with pytest.raises(ValidationError): ReviewData.model_validate(data)

def test_review_requires_party_role():
    data = _review()
    del data['parties'][0]['role']
    with pytest.raises(ValidationError): ReviewData.model_validate(data)

def test_explicit_review_values_accepted():
    reviewed = ReviewData.model_validate(_review())
    assert reviewed.contract.currency == 'CAD'
    assert reviewed.parties[0].role == 'cedant'

def test_manual_contract_create_default_unchanged():
    from app.schemas.contract import ContractCreate
    data = _review()['contract']
    del data['currency']
    assert ContractCreate.model_validate(data).currency == 'USD'


def test_review_refuses_blank_new_party_name():
    data = _review()
    data['parties'][0]['party_data']['name'] = '   '
    with pytest.raises(ValidationError): ReviewData.model_validate(data)
