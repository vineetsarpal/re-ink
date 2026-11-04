"""Deterministic synthetic originals, authored independently of provider output.

Run with the Codex bundled Python (reportlab, Pillow, python-docx).
Sources and expected.json are the ground truth; this script never calls providers.
"""
from pathlib import Path
from datetime import datetime, timezone
import io
import hashlib
import json
import zipfile
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).parent
COMMON = [
    'Reinsurance Contract',
    'Contract number: SYN-001',
    'Contract name: Synthetic Cedar Treaty',
    'Effective date: 2027-01-01',
    'Expiration date: 2027-12-31',
    'Currency: USD',
    'Premium: USD 120000',
    'Coverage limit: USD 2000000',
    'Deductible: USD 10000',
    'Cedant: Cedar Example Insurance Ltd',
    'Reinsurer: Harbor Example Re Ltd',
    'Type: Quota Share',
    'This contract reinsures the cedant property portfolio.',
]
SOURCES = {
    'ordinary': COMMON,
    'scanned': COMMON,
    'docx': [x.replace('SYN-001', 'SYN-003') for x in COMMON],
    'ambiguous': [
        'Reinsurance Contract', 'Contract number: SYN-004',
        'Contract name: Synthetic Ambiguous Treaty',
        'Effective date may be 03/04/2027; day/month order is unspecified.',
        'Expiration date: 2027-12-31',
        'Premium proposed at $100000; denomination is not specified.',
        'Cedant: Cedar Example Insurance Ltd',
        'Reinsurer: Harbor Example Re Ltd',
        'No currency is agreed. No binding effective date is agreed.',
    ],
    'multiple': COMMON[:1] + [x.replace('SYN-001', 'SYN-005') for x in COMMON[1:]] + [
        'Broker: Maple Example Brokers Ltd',
        'Additional reinsurer: Summit Example Re Ltd',
    ],
    'unreadable': [],
}
FIELDS = {
    'contract_number': 'SYN-001', 'contract_name': 'Synthetic Cedar Treaty',
    'effective_date': '2027-01-01', 'expiration_date': '2027-12-31',
    'currency': 'USD', 'premium_amount': 120000, 'limit_amount': 2000000,
    'retention_amount': 10000, 'contract_sub_type': 'quota_share',
}
PARTIES = [
    {'name': 'Cedar Example Insurance Ltd', 'role': 'cedant'},
    {'name': 'Harbor Example Re Ltd', 'role': 'reinsurer'},
]

def expected():
    cases = []
    for name, lines in SOURCES.items():
        fields = dict(FIELDS)
        parties = list(PARTIES)
        if name == 'docx': fields['contract_number'] = 'SYN-003'
        if name == 'multiple':
            fields['contract_number'] = 'SYN-005'
            parties += [{'name': 'Maple Example Brokers Ltd', 'role': 'broker'},
                        {'name': 'Summit Example Re Ltd', 'role': 'reinsurer'}]
        missing = []
        ambiguous = []
        if name == 'ambiguous':
            fields = {'contract_number': 'SYN-004', 'contract_name': 'Synthetic Ambiguous Treaty',
                      'expiration_date': '2027-12-31'}
            missing = ['currency', 'limit_amount', 'retention_amount', 'contract_sub_type']
            ambiguous = ['effective_date', 'premium_amount']
        if name == 'unreadable': fields, parties = {}, []
        cases.append({'case_id': name, 'file': name + ('.docx' if name == 'docx' else '.pdf'),
                      'expected_outcome': 'failed' if name == 'unreadable' else 'completed',
                      'fields': fields, 'missing_fields': missing, 'ambiguous_fields': ambiguous,
                      'parties': parties, 'source_lines': lines,
                      'evidence': {'manual_verification_required': True,
                                   'coordinates_expected': name not in ('docx', 'unreadable'),
                                   'page_number': None if name == 'docx' else 1,
                                   'quotes_available': lines,
                                   'boxes': 'Check any supplied boxes against original; no guessed ground-truth rectangles.'}})
    return {'schema_version': 1, 'authorship': 'Synthetic source and expected values authored before any provider execution; never derived from provider output.',
            'human_ground_truth_review': 'pending', 'live_provider_executions': 0, 'cases': cases}


def create_pdf(path, lines, scan=False):
    c = canvas.Canvas(str(path), pagesize=(612, 792), invariant=1)
    if scan:
        image = Image.new('RGB', (1224, 1584), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 24)
        for n, line in enumerate(lines): draw.text((100, 120 + 52*n), line, fill='black', font=font)
        c.drawImage(ImageReader(image), 0, 0, width=612, height=792)
    else:
        c.setFont('Helvetica', 12)
        for n, line in enumerate(lines): c.drawString(50, 732 - 26*n, line)
    c.showPage()
    c.save()


if __name__ == '__main__':
    # Persist author-written expectations before creating originals and long before providers run.
    (ROOT / 'expected.json').write_text(json.dumps(expected(), indent=2) + '\n')
    for name, lines in SOURCES.items():
        if name == 'docx':
            doc = Document()
            doc.core_properties.author = 're-ink synthetic corpus'
            doc.core_properties.created = datetime(2026, 10, 16, tzinfo=timezone.utc)
            doc.core_properties.modified = doc.core_properties.created
            doc.sections[0].top_margin = Inches(0.7)
            doc.styles['Normal'].font.size = Pt(11)
            for style_name in ('Normal', 'Title'):
                doc.styles[style_name].font.color.rgb = RGBColor(0, 0, 0)
                for border in list(doc.styles[style_name].element.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr')):
                    border.getparent().remove(border)
            doc.add_paragraph(lines[0], 'Title')
            for line in lines[1:6]: doc.add_paragraph(line)
            table = doc.add_table(rows=0, cols=2, style='Table Grid')
            for line in lines[6:12]:
                key, value = line.split(': ', 1)
                cells = table.add_row().cells
                cells[0].text, cells[1].text = key, value
            doc.add_paragraph(lines[12])
            data = io.BytesIO()
            doc.save(data)
            # Stable ZIP timestamps avoid regenerations changing corpus hashes.
            with zipfile.ZipFile(data) as source, zipfile.ZipFile(ROOT / 'docx.docx', 'w', zipfile.ZIP_DEFLATED) as out:
                for item in source.infolist():
                    item.date_time = (2026, 10, 16, 0, 0, 0)
                    out.writestr(item, source.read(item.filename))
        else: create_pdf(ROOT / (name + '.pdf'), lines, scan=name == 'scanned')

    (ROOT / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in sorted(ROOT.iterdir()) if p.suffix in ('.pdf', '.docx')))
