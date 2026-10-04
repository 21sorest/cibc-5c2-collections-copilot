"""Parent-process checks for isolated local adapter inference; no GPU required."""
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import trained_llm as adapter
from train_llm import target


class AdapterPromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        paths = {'ROOT': root, 'ADAPTER': root / 'adapter', 'BASE': root / 'base',
                 'CORPUS': root / 'corpus', 'PYTHON': root / 'python.exe'}
        for name, path in paths.items():
            patcher = patch.object(adapter, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('ADAPTER', 'BASE', 'CORPUS'):
            paths[name].mkdir()
        (root / 'reports').mkdir()
        paths['PYTHON'].write_bytes(b'test-only-placeholder')
        self.weights = paths['ADAPTER'] / 'adapter_model.safetensors'
        self.weights.write_bytes(b'original-test-adapter')
        self.provenance = paths['BASE'] / 'provenance.json'
        self.provenance.write_text('{"revision":"test-revision"}', encoding='utf-8')
        self.corpus = paths['CORPUS'] / 'test.jsonl'
        self.corpus.write_text('{"id":"held-out-test"}\n', encoding='utf-8')
        instruction_hash = hashlib.sha256(adapter.INSTRUCTIONS.encode()).hexdigest()
        self.report = {'adapter': True, 'split': 'test', 'unique_cases': 30, 'examples': 120,
                       'complete_rate': 1, 'grounded_rate': 1, 'instructions_sha256': instruction_hash,
                       'adapter_sha256': adapter.sha(self.weights),
                       'base_provenance_sha256': adapter.sha(self.provenance),
                       'corpus_sha256': adapter.sha(self.corpus)}
        training = {'adapter_sha256': self.report['adapter_sha256'],
                    'instructions_sha256': instruction_hash,
                    'corpus': {'hashes': {'test': self.report['corpus_sha256']}}}
        (root / 'reports/llm_training.json').write_text(json.dumps(training), encoding='utf-8')
        self.report_path = root / 'reports/llm_adapter_test.json'
        self.save_report(self.report)

    def save_report(self, report):
        self.report_path.write_text(json.dumps(report), encoding='utf-8')

    def test_only_bound_successful_final_report_enables_adapter(self):
        self.assertTrue(adapter.available())
        for field, value in [('adapter', False), ('split', 'dev'), ('unique_cases', 29),
                             ('examples', 119), ('complete_rate', 0.99),
                             ('instructions_sha256', 'old-prompt'), ('adapter_sha256', 'old-weights')]:
            with self.subTest(field=field):
                self.save_report({**self.report, field: value})
                self.assertFalse(adapter.available())
        self.save_report(self.report)
        self.assertTrue(adapter.available())

    def test_artifact_replacement_invalidates_old_evaluation(self):
        for path in (self.weights, self.provenance, self.corpus):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b' changed')
                self.assertFalse(adapter.available())
                path.write_bytes(original)
                self.assertTrue(adapter.available())

    def test_report_without_training_manifest_stays_experimental(self):
        (adapter.ROOT / 'reports/llm_training.json').unlink()
        self.assertFalse(adapter.available())

    def test_nondictionary_report_or_training_file_stays_experimental(self):
        for body in (None, [], 'unexpected-string'):
            with self.subTest(body=body):
                self.save_report(body)
                self.assertFalse(adapter.available())
        self.save_report(self.report)
        (adapter.ROOT / 'reports/llm_training.json').write_text('null', encoding='utf-8')
        self.assertFalse(adapter.available())


class AdapterInferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'reports').mkdir()
        (self.root / 'reports/llm_training.json').write_text(
            json.dumps({'adapter_sha256': 'recorded-adapter-hash'}), encoding='utf-8')
        self.bundle = {'case': {'case_id': 'CS-TEST', 'case_status': 'open',
                                'total_overdue_cad': '125.40', 'current_dpd': 12}}
        self.evidence = {'case:CS-TEST': {'case_status': 'open',
                                         'total_overdue_cad': '125.40', 'current_dpd': '12'}}
        self.brief = {'summary': 'original', 'sources': ['original-source'],
                      'contact_gate': {'allowed': False}, 'proposed_step': 'review'}

    def invoke(self, result=None, error=None):
        with patch.object(adapter, 'ROOT', self.root), patch.object(adapter, 'available', return_value=True):
            with patch.object(adapter.subprocess, 'run', return_value=result, side_effect=error) as runner:
                value = adapter.enhance_summary(self.bundle, self.brief)
                return value, runner

    def assert_temporary_inputs_removed(self):
        self.assertEqual(list((self.root / 'tmp').glob('*.json')), [])

    def test_success_preserves_gate_and_step_and_renders_verified_values(self):
        result = SimpleNamespace(returncode=0, stdout=json.dumps({'output': target(self.evidence)}))
        drafted, runner = self.invoke(result)
        self.assertEqual(drafted['contact_gate'], self.brief['contact_gate'])
        self.assertEqual(drafted['proposed_step'], 'review')
        self.assertEqual(self.brief['summary'], 'original')
        self.assertIn('Case overdue CAD: 125.40.', drafted['summary'])
        self.assertTrue(drafted['ai_metadata']['team_finetuned'])
        self.assertFalse(drafted['ai_metadata']['trained_from_scratch'])
        args, kwargs = runner.call_args
        self.assertIn('--adapter', args[0])
        self.assertEqual(kwargs['timeout'], 60)
        self.assertTrue(kwargs['capture_output'])
        self.assert_temporary_inputs_removed()

    def test_parent_rejects_wrong_cited_value_even_if_child_exits_successfully(self):
        body = target(self.evidence)
        body['facts'][1]['value'] = '12'
        with self.assertRaisesRegex(ValueError, 'complete factual grounding'):
            self.invoke(SimpleNamespace(returncode=0, stdout=json.dumps({'output': body})))
        self.assertEqual(self.brief['summary'], 'original')
        self.assert_temporary_inputs_removed()

    def test_parent_rejects_missing_required_field(self):
        body = target(self.evidence)
        body['facts'].pop()
        with self.assertRaisesRegex(ValueError, 'complete factual grounding'):
            self.invoke(SimpleNamespace(returncode=0, stdout=json.dumps({'output': body})))
        self.assert_temporary_inputs_removed()

    def test_timeout_keeps_fallback_and_removes_input(self):
        with self.assertRaisesRegex(ValueError, 'preserve the deterministic brief'):
            self.invoke(error=subprocess.TimeoutExpired('draft', 60))
        self.assertEqual(self.brief['summary'], 'original')
        self.assert_temporary_inputs_removed()

    def test_invalid_child_stdout_keeps_fallback(self):
        with self.assertRaisesRegex(ValueError, 'preserve the deterministic brief'):
            self.invoke(SimpleNamespace(returncode=0, stdout='debug text before JSON'))
        self.assert_temporary_inputs_removed()

    def test_experimental_adapter_does_not_start_subprocess(self):
        with patch.object(adapter, 'available', return_value=False), patch.object(adapter.subprocess, 'run') as runner:
            with self.assertRaisesRegex(ValueError, 'experimental'):
                adapter.enhance_summary(self.bundle, self.brief)
            runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
