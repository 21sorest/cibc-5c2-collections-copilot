"""Optional isolated GPU adapter inference; the main app keeps its base environment."""
import hashlib
import json
import subprocess
import tempfile
import time

from llm import canonical_value, validate_facts
from pipeline import ROOT
from train_llm import ADAPTER, BASE, CORPUS, FIELDS, INSTRUCTIONS, score_output, sha

PYTHON = ROOT / '.venv-training/Scripts/python.exe'


def available():
    path = ROOT / 'reports/llm_adapter_test.json'
    if not PYTHON.exists() or not ADAPTER.exists() or not path.exists():
        return False
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
        training = json.loads((ROOT / 'reports/llm_training.json').read_text(encoding='utf-8'))
        if not isinstance(report, dict) or not isinstance(training, dict):
            return False
        digest = sha(ADAPTER / 'adapter_model.safetensors')
        return (report.get('adapter') is True and report.get('split') == 'test'
            and report.get('unique_cases', 0) >= 30 and report.get('examples') == report.get('unique_cases', 0) * 4
            and report.get('complete_rate') == 1 and report.get('grounded_rate') == 1
            and report.get('instructions_sha256') == training.get('instructions_sha256') == hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()
            and report.get('adapter_sha256') == training.get('adapter_sha256') == digest
            and report.get('base_provenance_sha256') == sha(BASE / 'provenance.json')
            and report.get('corpus_sha256') == training['corpus']['hashes']['test'] == sha(CORPUS / 'test.jsonl'))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def enhance_summary(bundle, brief):
    if not available():
        raise ValueError('The local fine-tuned adapter is still experimental or its final checks are unavailable.')
    case = bundle['case']
    evidence = {'case:' + case['case_id']: {field: canonical_value(case[field]) for field in FIELDS}}
    tick = time.monotonic()
    folder = ROOT / 'tmp'
    folder.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json', dir=folder, delete=False) as handle:
        json.dump(evidence, handle)
        path = handle.name
    try:
        result = subprocess.run([str(PYTHON), str(ROOT / 'train_llm.py'), 'draft', '--adapter', '--input', path],
            capture_output=True, text=True, encoding='utf-8', timeout=60, cwd=ROOT)
        if result.returncode:
            raise ValueError('The GPU adapter draft failed; preserve the deterministic brief.')
        output = json.loads(result.stdout)['output']
        if not score_output(json.dumps(output), evidence)['complete']:
            raise ValueError('The adapter draft failed complete factual grounding.')
        facts = validate_facts(output, evidence)
    except (subprocess.TimeoutExpired, OSError, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError('The local adapter is unavailable; preserve the deterministic brief.') from None
    finally:
        from pathlib import Path
        Path(path).unlink(missing_ok=True)
    drafted = dict(brief)
    drafted['summary'] = ' '.join(f"{fact['text']} [{', '.join(fact['sources'])}]" for fact in facts)
    drafted['sources'] = list(dict.fromkeys(brief['sources'] + list(evidence)))
    drafted['generator'] = 'local:Qwen2.5-0.5B-Instruct-team-LoRA'
    report = json.loads((ROOT / 'reports/llm_training.json').read_text(encoding='utf-8'))
    drafted['ai_metadata'] = {'team_finetuned': True, 'trained_from_scratch': False,
        'adapter_sha256': report['adapter_sha256'], 'input_sha256': hashlib.sha256(json.dumps(evidence).encode()).hexdigest(),
        'latency_seconds_including_load': round(time.monotonic() - tick, 3),
        'validation': 'Exact cited values and complete required fields; deterministic rendering; employee review required'}
    return drafted
