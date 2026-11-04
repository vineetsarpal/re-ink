#!/usr/bin/env python3
"""Offline scoring of recorded synthetic runs. Never contacts a provider.

Input JSONL contains every attempted execution, including failures and reruns:
{"case_id":"ordinary", "provider":"openai", "mode":"fixture", "run_id":"...",
 "release":"...", "model":"...", "job_id":"...", "attempt_id":"...",
 "workflow_execution_id":"...", "status":"completed", "result":{...}}
Pass original normalized v1 result shape, not a provider's raw JSON. Label tests
mode=fixture. mode=live is operator attestation, not independently verified here.
Manual original/citation audit and corrections remain separate from scalar scores.
"""
import argparse
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'backend/tests/corpus/expected.json'
NUMERIC = {'premium_amount', 'limit_amount', 'retention_amount', 'commission_rate'}
DATES = {'effective_date', 'expiration_date', 'inception_date'}


def normalize(key, value):
    if value is None or value == '': return None
    if key in NUMERIC:
        if isinstance(value, bool): return ('invalid-number', str(value))
        try: return Decimal(str(value).replace(',', '').strip()).normalize()
        except InvalidOperation: return ('invalid-number', str(value))
    if key in DATES:
        try: return date.fromisoformat(str(value)).isoformat()
        except ValueError: return ('invalid-date', str(value))
    if key == 'currency': return str(value).strip().upper()
    return str(value).strip()


def evaluate(run, expected):
    required = ('case_id', 'provider', 'mode', 'run_id', 'release', 'model', 'job_id', 'attempt_id', 'workflow_execution_id', 'status')
    if any(not isinstance(run.get(k), str) or not run[k] for k in required):
        raise ValueError('Every run needs nonempty identifying metadata, provider, mode and status')
    if run['provider'] not in ('landingai', 'openai') or run['mode'] not in ('fixture', 'live'):
        raise ValueError('provider must be landingai/openai and mode fixture/live')
    if run['status'] not in ('completed', 'failed', 'timed_out'):
        raise ValueError('Only recorded terminal outcomes may be evaluated')
    report = {k: run[k] for k in required}
    report['expected_outcome'] = expected['expected_outcome']
    report['case_outcome_matches'] = (run['status'] == expected['expected_outcome'])
    report['case_failure'] = run['status'] != 'completed'
    report['fields'] = {'denominator': 0, 'correct': 0, 'missing': 0, 'incorrect': 0, 'unexpected': 0, 'unsupported_invention': 0}
    report['parties'] = {'name_denominator': 0, 'role_denominator': 0, 'names_correct': 0, 'names_missing': 0, 'names_unexpected': 0, 'roles_correct': 0, 'roles_incorrect': 0, 'roles_missing': 0}
    report['evidence'] = {'fields_returned': 0, 'fields_with_source_text': 0, 'quote_literal_matches': 0,
                          'quote_literal_mismatches': 0, 'coordinate_fields_returned': 0,
                          'manual_audit': 'NOT RUN; literal matching does not prove field support or box fidelity'}
    report['details'] = []
    if run['status'] != 'completed':
        report['error_code'] = run.get('error_code')
        return report
    result = run.get('result')
    if not isinstance(result, dict) or not isinstance(result.get('contract_data'), dict) or not isinstance(result.get('parties_data'), list):
        raise ValueError('Completed run requires normalized contract_data and parties_data')
    actual = result['contract_data']
    counters = report['fields']
    for key, value in expected['fields'].items():
        counters['denominator'] += 1
        observed = normalize(key, actual.get(key))
        verdict = 'missing' if observed is None else ('correct' if observed == normalize(key, value) else 'incorrect')
        counters[verdict] += 1
        if verdict != 'correct': report['details'].append({'field': key, 'verdict': verdict, 'expected': value, 'observed': actual.get(key)})
    for key, value in actual.items():
        if normalize(key, value) is None or key in expected['fields']: continue
        counters['unexpected'] += 1
        if key in expected['missing_fields'] + expected['ambiguous_fields'] or expected['expected_outcome'] == 'failed':
            counters['unsupported_invention'] += 1
            report['details'].append({'field': key, 'verdict': 'unsupported_invention', 'observed': value})
        else:
            report['details'].append({'field': key, 'verdict': 'unexpected_requires_manual_source_review', 'observed': value})
    expected_parties = expected['parties']
    actual_parties = result['parties_data']
    if any(not isinstance(p, dict) for p in actual_parties): raise ValueError('Each party must be an object')
    names = Counter(p.get('name', '').strip() for p in actual_parties)
    roles = Counter((p.get('name', '').strip(), p.get('role')) for p in actual_parties)
    pc = report['parties']
    for party in expected_parties:
        pc['name_denominator'] += 1; pc['role_denominator'] += 1
        if names[party['name']]:
            pc['names_correct'] += 1; names[party['name']] -= 1
            pair = (party['name'], party['role'])
            if roles[pair]: pc['roles_correct'] += 1; roles[pair] -= 1
            else: pc['roles_incorrect'] += 1
        else: pc['names_missing'] += 1; pc['roles_missing'] += 1
    pc['names_unexpected'] = sum(names.values())
    sources = result.get('field_sources') or {}
    contract_sources = sources.get('contract') or {}
    party_sources = sources.get('parties') or []
    report['evidence']['party_sources_aligned'] = len(party_sources) == len(actual_parties) if sources else None
    report['evidence']['expected_contract_field_denominator'] = len(expected['fields'])
    report['evidence']['expected_contract_fields_with_source_text'] = sum(bool((contract_sources.get(k) or {}).get('source_text')) for k in expected['fields'])
    report['evidence']['expected_contract_fields_without_source_text'] = len(expected['fields']) - report['evidence']['expected_contract_fields_with_source_text']
    report['evidence']['expected_party_name_denominator'] = len(expected_parties)
    text = '\n'.join(expected['source_lines'])
    for source in list(contract_sources.values()) + [s for p in party_sources for s in p.values()]:
        report['evidence']['fields_returned'] += 1
        if source.get('source_text'):
            report['evidence']['fields_with_source_text'] += 1
            key = 'quote_literal_matches' if source['source_text'] in text else 'quote_literal_mismatches'
            report['evidence'][key] += 1
        if source.get('bbox') is not None or source.get('page_number') is not None:
            report['evidence']['coordinate_fields_returned'] += 1
    report['evidence']['openai_untrusted_grounding_returned'] = run['provider'] == 'openai' and bool(sources or result.get('confidence_score') is not None)
    report['evidence']['docx_coordinates_returned'] = expected['case_id'] == 'docx' and report['evidence']['coordinate_fields_returned'] > 0
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', type=Path)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = {case['case_id']: case for case in json.loads(args.manifest.read_text())['cases']}
    runs = [json.loads(line) for line in args.runs.read_text().splitlines() if line.strip()]
    ids = [r.get('run_id') for r in runs]
    if len(set(ids)) != len(ids): raise ValueError('run_id must be unique; record reruns separately')
    reports = [evaluate(run, cases[run['case_id']]) for run in runs]
    coverage = {provider: {mode: sorted({r['case_id'] for r in reports if r['provider'] == provider and r['mode'] == mode})
                          for mode in ('fixture', 'live')} for provider in ('landingai', 'openai')}
    args.output.write_text(json.dumps({'reports': reports, 'coverage': coverage,
        'live_attestation': 'mode=live comes from the operator; this offline script cannot prove provider execution',
        'manual_quality_and_citation_audit': 'NOT RUN', 'production_accuracy_claim': None}, indent=2) + '\n')

if __name__ == '__main__': main()
