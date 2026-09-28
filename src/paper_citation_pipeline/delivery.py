"""Self-contained, compressed cloud JSON; fail-closed local delivery gate.

This module never uploads anything and never deletes a PDF. A passing automated
check is not a population accuracy estimate or a full-fidelity PDF replacement.
"""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from .config import read_json, digest as file_digest
from .numbering import atomic_json
from .local_review import canonical, digest, gate

SCHEMA = 'paper-citation-cloud/1'


def seal(packet):
    review = packet['local_verification']
    review['packet_sha256'] = digest({k: v for k, v in packet.items() if k != 'local_verification'})
    review['review_sha256'] = digest({k: v for k, v in review.items() if k not in {'packet_sha256', 'review_sha256'}})


def blockers(packet):
    review = packet.get('local_verification', {})
    problems = []
    if review.get('packet_sha256') != digest({k: v for k, v in packet.items() if k != 'local_verification'}):
        problems.append('verification_stale_or_missing')
    if review.get('review_sha256') != digest({k: v for k, v in review.items() if k not in {'packet_sha256', 'review_sha256'}}):
        problems.append('verification_record_changed')
    checked = gate(packet, review.get('references', {}), review.get('reference_regions', {}), review.get('contexts', {}))
    problems.extend(x['code'] for x in checked['blockers'])
    if review.get('status') != 'passed' or review.get('upload_eligible') is not True:
        problems.append('local_verification_not_passed')
    return sorted(set(problems))


def compact(packet):
    """Retain text evidence + Docling structure, excluding duplicate parser internals.

Long identical strings are interned, so repeated paragraphs/reference strings are
stored once. decode() reconstructs the payload without a PDF, TEI or local path.
Image bytes are not embedded; this is explicitly a textual citation archive.
"""
    keys = ('paper_id', 'document_id', 'page_count', 'target', 'metadata', 'numbering',
            'citation_index', 'pdf_pages', 'target_candidates', 'organization_attributions',
            'unresolved', 'corrections', 'target_pdf_mentions', 'reference_region_audit',
            'recall_audit', 'target_coverage', 'quality', 'language', 'local_verification', 'metadata_review', 'mention_review')
    payload = {k: deepcopy(packet[k]) for k in keys if k in packet}
    payload['source'] = {'filename': Path(packet['source']['pdf']).name, 'sha256': packet['source']['sha256']}
    docling = packet.get('parser_result', {}).get('docling', {}).get('document', {})
    payload['document_structure'] = deepcopy(docling)
    payload['provenance'] = {k: deepcopy(v) for k, v in packet.get('provenance', {}).items() if k != 'artifacts'}
    # Replace local source/artifact locations by document-relative names. These
    # fields are provenance, never evidence text; do not rewrite text strings.
    def portable(obj):
        if isinstance(obj, list):
            return [portable(v) for v in obj]
        if isinstance(obj, dict):
            return {k: portable(v) for k, v in obj.items() if k not in
                    {'state_file', 'source_path', 'source_json', 'source_pdf', 'pdf', 'script_hashes', 'artifacts', 'image'}}
        return obj
    payload = portable(payload)
    texts, lookup = [], {}
    def intern(value):
        if isinstance(value, str) and len(value) >= 80:
            if value not in lookup:
                lookup[value] = len(texts)
                texts.append(value)
            return {'$text': lookup[value]}
        if isinstance(value, dict):
            if set(value) == {'$text'}:
                raise ValueError('Reserved cloud text-reference key in source')
            return {k: intern(v) for k, v in value.items()}
        if isinstance(value, list):
            return [intern(v) for v in value]
        return value
    packed = intern(payload)
    return {'schema': SCHEMA, 'evidence_scope': 'text_and_layout_not_original_images',
            'source_packet_sha256': digest(packet), 'decoded_sha256': digest(payload),
            'text_pool': texts, 'payload': packed}


def decode(archive):
    if archive.get('schema') != SCHEMA:
        raise ValueError('Unsupported cloud schema')
    pool = archive['text_pool']
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'$text'}:
                n = value['$text']
                if type(n) is not int or not 0 <= n < len(pool):
                    raise ValueError('Broken cloud text reference')
                return pool[n]
            return {k: expand(v) for k, v in value.items()}
        if isinstance(value, list):
            return [expand(v) for v in value]
        return value
    result = expand(archive['payload'])
    if digest(result) != archive['decoded_sha256']:
        raise ValueError('Cloud evidence hash mismatch')
    return result


def prepare_delivery(output, paths, workbook=None):
    """Create a single atomic ZIP only if every eligible paper and workbook pass.

Blocked runs invalidate their active delivery pointer; an old ZIP cannot be
mistaken for the current run. Prior ZIPs remain as explicitly historical files.
"""
    output = Path(output)
    paths = list(paths)
    packets = [read_json(p) for p in paths]
    report = {'schema': 'local-delivery/1', 'status': 'blocked', 'papers': [],
              'blockers': [], 'package': None, 'automatic_pdf_deletion_allowed': False,
              'accuracy_95_certified': False}
    for path, packet in zip(paths, packets):
        problems = blockers(packet)
        report['papers'].append({'paper': packet['paper_id'], 'packet_sha256': file_digest(path),
                                  'status': 'blocked' if problems else 'passed', 'blockers': problems})
    if not packets:
        report['blockers'].append('no_eligible_packets')
    if any(p['status'] != 'passed' for p in report['papers']):
        report['blockers'].append('papers_require_local_review')
    manifest_path = output / 'manifest.json'
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        expected = {m['paper'] for m in manifest if m['readiness'] != 'excluded'}
        if expected != {p['paper_id'] for p in packets} or any(m['readiness'] == 'failed' for m in manifest):
            report['blockers'].append('batch_incomplete')
    source_keys=[(p['source']['sha256'],p.get('target',{}).get('organization_id')) for p in packets]
    if len(source_keys)!=len(set(source_keys)):
        report['blockers'].append('duplicate_source_and_target')
    assets = []
    if workbook is None:
        report['blockers'].append('completed_workbook_required')
    else:
        workbook = Path(workbook)
        try:
            from .quality import inspect_workbook
            receipt, checks = inspect_workbook(workbook, expected_papers=len(packets))
            if any(c['status'] != 'pass' for c in checks):
                report['blockers'].append('workbook_checks_not_passed')
            receipt = read_json(workbook.with_suffix('.fill-manifest.json'))
            if set(receipt['paper_ids']) != {p.get('numbering', {}).get('paper_id', p['paper_id']) for p in packets}:
                report['blockers'].append('workbook_paper_ids_mismatch')
            provenance = read_json(workbook.with_suffix('.provenance.json'))
            # Export provenance must bind the workbook to these exact packets.
            # Compare directly below; no export, numbering allocation or model calls.
            sources = provenance.get('sources', {})
            expected_hashes = {file_digest(p) for p in paths}
            actual_hashes = set(sources.values())
            if actual_hashes != expected_hashes:
                report['blockers'].append('workbook_source_packets_mismatch')
            assets = [workbook, workbook.with_suffix('.fill-manifest.json')]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report['blockers'].append('workbook_verification_unavailable: ' + str(exc))
    output.mkdir(parents=True, exist_ok=True)
    if not report['blockers']:
        with tempfile.TemporaryDirectory(prefix='citation-delivery-', dir=output) as temp:
            temp = Path(temp)
            entries = []
            for packet in packets:
                archive = compact(packet)
                decode(archive)  # Local round-trip before originals can be removed.
                name = packet['source']['sha256'] + '-' + digest(packet['target'])[:12] + '.json.gz'
                contents = gzip.compress(canonical(archive).encode(), mtime=0)
                (temp / name).write_bytes(contents)
                # Reopen actual bytes, not just the in-memory structure.
                decode(json.loads(gzip.decompress((temp / name).read_bytes())))
                entries.append({'file': name, 'sha256': file_digest(temp / name),
                                'paper_id': packet['paper_id'], 'source_sha256': packet['source']['sha256']})
            manifest = {'schema': 'citation-delivery/1', 'papers': entries,
                        'accuracy_95_certified': False, 'pdfs_included': False,
                        'automatic_pdf_deletion_allowed': False,
                        'workbook': {'file': 'citations.xlsx', 'sha256': file_digest(workbook)}}
            atomic_json(temp / 'manifest.json', manifest)
            package = temp / 'package.zip'
            with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED) as z:
                z.write(temp / 'manifest.json', 'manifest.json')
                for entry in entries:
                    z.write(temp / entry['file'], 'json/' + entry['file'])
                for asset,name in zip(assets,['citations.xlsx','citations.fill-manifest.json']):
                    z.write(asset,name)
            fingerprint = file_digest(package)
            dest = output / ('upload-' + fingerprint[:16] + '.zip')
            package.replace(dest)
            report.update(status='ready', package=str(dest), package_sha256=fingerprint)
    atomic_json(output / 'upload-readiness.json', report)
    return report
