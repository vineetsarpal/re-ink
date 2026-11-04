"""Generate provider input/validation schema from backend release-owned models."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.schemas.workflow import ContractFacts, PartyFacts, CURRENCY_CODES, MAX_CALLBACK_BYTES, MAX_PARTIES

OUT = Path(__file__).parent / 'generated'

def strict(model):
    schema = model.model_json_schema()
    def clean(node):
        if isinstance(node, dict):
            node = {k: clean(v) for k, v in node.items() if k not in ('title', 'default')}
            if node.get('type') == 'object':
                node['additionalProperties'] = False
                node['required'] = list(node['properties'])
            return node
        if isinstance(node, list):
            return [clean(x) for x in node]
        return node
    return clean(schema)

contract, party = strict(ContractFacts), strict(PartyFacts)
contract['properties']['currency'] = {'anyOf': [{'type': 'string', 'enum': sorted(CURRENCY_CODES)}, {'type': 'null'}]}
for field in ('effective_date', 'expiration_date', 'inception_date'):
    contract['properties'][field]['anyOf'][0]['description'] = 'Real calendar date in YYYY-MM-DD, otherwise null.'
schema = {'type': 'object', 'additionalProperties': False,
          'properties': {'contract_data': contract, 'parties_data': {'type': 'array', 'maxItems': MAX_PARTIES, 'items': party}},
          'required': ['contract_data', 'parties_data']}
OUT.mkdir(exist_ok=True)
(OUT / 'business-schema.json').write_text(json.dumps(schema, indent=2) + '\n')
(OUT / 'limits.json').write_text(json.dumps({'maxCallbackBytes': MAX_CALLBACK_BYTES}, indent=2) + '\n')
