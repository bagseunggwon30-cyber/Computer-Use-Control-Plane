"""Classify one pinned, observed historical startup defect, never general failure."""
import hashlib
import json
import os
from pathlib import Path
import re

from helper_process_evidence import require_success

SOURCE_RAW_SHA256 = '31742c3a48c3305f26751ea9c3b8b8db5592a0aa5f192ccdfea5795252731e81'
SOURCE_NORMALIZED_SHA256 = '173c5cde4c9ef282835d5add1e3e11fbf9f0756a7aed359750b00030f32ab7a8'
OBSERVED_STDERR_SHA256 = 'e1de6715702675a2c502e1341d79d97c09b0a7db02f0e58d93f066d99e8978cb'
OBSERVATION = Path(__file__).resolve().parents[1] / 'fixtures/legacy-helper/observed-startup.stderr.bin'


def _diagnostic(raw):
    # Only the owned source filename prefix and formatting whitespace vary.
    # The entire remaining English PS5 diagnostic must match the observed one.
    text = raw.decode('utf-8-sig', errors='strict')
    match = re.fullmatch(r'([^\r\n]+\.ps1) : (.+)', text, re.DOTALL)
    if match is None:
        raise AssertionError('Unexpected original startup diagnostic shape')
    return match[1], ' '.join(match[2].split())


def classify_original_startup(result, *, source, lock, process_returncode):
    require_success(result, expected_exit=1)
    evidence = Path(result['evidence_path'])
    for name in ('stdout', 'stderr'):
        if (result['bytes_observed'][name] != len(result[name]) or len(result[name]) > 262144 or
                evidence.with_suffix('.' + name + '.bin').read_bytes() != result[name]):
            raise AssertionError('Original startup raw evidence is incomplete or changed')
    if process_returncode != 1 or result['stdout'] or lock.exists():
        raise AssertionError('Original startup left unexpected process, output or lock effects')
    raw = source.read_bytes()
    normalized = raw.decode('utf-8-sig').replace('\r\n', '\n').encode('utf-8')
    if (hashlib.sha256(raw).hexdigest() != SOURCE_RAW_SHA256 or
            hashlib.sha256(normalized).hexdigest() != SOURCE_NORMALIZED_SHA256):
        raise AssertionError('Original startup source pin changed')
    retained = OBSERVATION.read_bytes()
    if len(retained) != 499 or hashlib.sha256(retained).hexdigest() != OBSERVED_STDERR_SHA256:
        raise AssertionError('Retained original startup evidence changed')
    path, diagnostic = _diagnostic(result['stderr'])
    if not os.path.samefile(path, source) or diagnostic != _diagnostic(retained)[1]:
        raise AssertionError('Unexpected original startup failure')
    return dict(schema='cucp.helper-baseline-observation/v1', status='baseline-startup-defect',
                raw_oracle_status='failed', original_startup_qualified=False,
                source_raw_sha256=SOURCE_RAW_SHA256, source_normalized_sha256=SOURCE_NORMALIZED_SHA256,
                source_line=534, observed_exit_code=1, owned_process_remaining=False, owned_lock_remaining=False,
                stdout_sha256=hashlib.sha256(result['stdout']).hexdigest(),
                stderr_sha256=hashlib.sha256(result['stderr']).hexdigest(), raw_evidence=result['evidence_path'],
                impact='Candidate makes the documented service reachable where the original aborts before publishing its lock.')


def save_classification(value, raw_evidence_path):
    destination = Path(raw_evidence_path).with_suffix('.classification.json')
    destination.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    return destination
