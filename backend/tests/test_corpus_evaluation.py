"""Scorer mechanics only; outputs never count as provider evaluation evidence."""
import importlib.util
import json
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('evaluate_corpus', ROOT/'scripts/evaluate_corpus.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CASES = {c['case_id']: c for c in json.loads((ROOT/'backend/tests/corpus/expected.json').read_text())['cases']}

def run(case):
    return {'case_id': case, 'provider': 'openai', 'mode': 'fixture', 'run_id': 'fixture',
            'release': 'fixture', 'model': 'fixture', 'job_id': 'fixture', 'attempt_id': 'fixture',
            'workflow_execution_id': 'fixture', 'status': 'completed',
            'result': {'contract_data': {}, 'parties_data': []}}

def test_corpus_has_six_originals_and_actual_image_only_scan():
    assert len(CASES) == 6
    for case in CASES.values(): assert (ROOT/'backend/tests/corpus'/case['file']).is_file()
    scanned = PdfReader(ROOT/'backend/tests/corpus/scanned.pdf').pages[0]
    assert not scanned.extract_text().strip()
    assert len(scanned.images) == 1
    assert not PdfReader(ROOT/'backend/tests/corpus/unreadable.pdf').pages[0].extract_text().strip()
    assert 'Synthetic Cedar Treaty' in PdfReader(ROOT/'backend/tests/corpus/ordinary.pdf').pages[0].extract_text()

def test_normalized_scalar_counts_missing_and_wrong_separately():
    data = run('ordinary')
    data['result']['contract_data'] = dict(CASES['ordinary']['fields'], currency='usd', premium_amount='120,000.00', contract_name='Wrong')
    data['result']['contract_data'].pop('contract_number')
    report = module.evaluate(data, CASES['ordinary'])
    assert report['fields'] == {'denominator': 9, 'correct': 7, 'missing': 1, 'incorrect': 1, 'unexpected': 0, 'unsupported_invention': 0}
    assert report['parties']['names_missing'] == 2
    assert report['evidence']['fields_returned'] == 0

def test_ambiguous_facts_and_unreadable_success_not_hidden():
    data = run('ambiguous')
    data['result']['contract_data'] = dict(CASES['ambiguous']['fields'], currency='USD', effective_date='2027-03-04')
    assert module.evaluate(data, CASES['ambiguous'])['fields']['unsupported_invention'] == 2
    data = run('unreadable')
    assert module.evaluate(data, CASES['unreadable'])['case_outcome_matches'] is False
    data['status'] = 'failed'; data.pop('result')
    report = module.evaluate(data, CASES['unreadable'])
    assert report['fields']['denominator'] == 0 and report['case_outcome_matches']
