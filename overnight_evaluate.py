"""Sequential local evaluation and artifact refresh, independent of chat availability.

Run after train_llm.py train finishes. No keys, uploads, paid calls or test tuning.
Writes stage state so a later chat can inspect and resume unfinished work.
"""
import json
import subprocess
import sys
import time
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRAIN = ROOT / '.venv-training/Scripts/python.exe'
BASE = ROOT / '.venv/Scripts/python.exe'
NODE = Path('C:/Users/desai/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
STATE = ROOT / 'reports/overnight_evaluation_state.json'


def state(body):
    body['updated_utc'] = datetime.now(timezone.utc).isoformat()
    STATE.write_text(json.dumps(body, indent=2), encoding='utf-8')


def main():
    # Wait for the separately running v1 development comparison; do not contend for the GPU.
    waiting = ROOT / 'reports/llm_adapter_dev.json'
    deadline = time.monotonic() + 1200
    state({'status': 'running', 'stage': 'await_v1_dev', 'completed': []})
    while not waiting.exists():
        if time.monotonic() > deadline:
            state({'status': 'failed', 'stage': 'await_v1_dev', 'completed': [], 'reason': 'Development report did not complete in 20 minutes'})
            return 1
        time.sleep(5)
    # Preserve the initial candidate and reports. Revision uses training data only;
    # no final test has been opened or used to tune parameters.
    initial = ROOT / 'data/models/case_facts_lora_v1'
    if not initial.exists():
        shutil.copytree(ROOT / 'data/models/case_facts_lora', initial)
        shutil.copy2(ROOT / 'reports/llm_training.json', ROOT / 'reports/llm_training_v1.json')
        shutil.copy2(waiting, ROOT / 'reports/llm_adapter_dev_v1.json')
        shutil.copytree(ROOT / 'data/llm_training', ROOT / 'data/llm_training_v1')
    stages = [
        ('robust_corpus', BASE, ['train_llm.py', 'prepare', '--robust']),
        ('robust_training', TRAIN, ['train_llm.py', 'train', '--epochs', '2']),
        ('adapter_dev', TRAIN, ['train_llm.py', 'evaluate', '--split', 'dev', '--limit', '30', '--adapter']),
        ('base_source_hint', TRAIN, ['train_llm.py', 'evaluate-source-hint', '--limit', '10']),
        ('adapter_source_hint', TRAIN, ['train_llm.py', 'evaluate-source-hint', '--limit', '10', '--adapter']),
        ('base_final', TRAIN, ['train_llm.py', 'evaluate', '--split', 'test', '--limit', '117']),
        ('adapter_final', TRAIN, ['train_llm.py', 'evaluate', '--split', 'test', '--limit', '117', '--adapter']),
        ('benchmark_answers', BASE, ['questions.py', '--benchmark']),
        ('benchmark_dev', BASE, ['evaluate_benchmarks.py']),
        ('all_tests', BASE, ['-m', 'unittest', '-q', 'test_pipeline', 'test_workflows', 'test_conversation',
            'test_classifier_split', 'test_audio_cache', 'test_llm_grounding', 'test_llm_training',
            'test_trained_llm', 'test_review_integrity', 'test_questions', 'test_preparation_study', 'test_ui']),
        ('pitch_pptx', NODE, ['docs/build_deck.mjs']),
        ('pitch_pdf', BASE, ['docs/export_deck_pdf.py']),
        ('brief_pptx', NODE, ['docs/build_rubric_brief.mjs']),
        ('brief_pdf', BASE, ['docs/export_rubric_brief_pdf.py']),
    ]
    completed = []
    for name, binary, arguments in stages:
        log = ROOT / ('tmp/overnight_' + name + '.log')
        state({'status': 'running', 'stage': name, 'completed': completed, 'log': str(log)})
        print(name, flush=True)
        with log.open('w', encoding='utf-8') as handle:
            result = subprocess.run([str(binary), *arguments], cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
        if result.returncode:
            state({'status': 'failed', 'stage': name, 'completed': completed, 'log': str(log), 'returncode': result.returncode})
            return result.returncode
        if name == 'robust_corpus':
            original = json.loads((ROOT / 'data/llm_training_v1/manifest.json').read_text(encoding='utf-8'))
            current = json.loads((ROOT / 'data/llm_training/manifest.json').read_text(encoding='utf-8'))
            if any(original['hashes'][split] != current['hashes'][split] for split in ('dev', 'test')):
                state({'status': 'failed', 'stage': name, 'completed': completed, 'reason': 'Held-out corpus changed during training-only augmentation'})
                return 2
        completed.append(name)
    state({'status': 'complete', 'completed': completed,
        'pending': 'Inspect model comparison, actual adapter app draft, deck page renders and updated docs. Human submission steps remain.'})
    return 0


if __name__ == '__main__':
    sys.exit(main())
