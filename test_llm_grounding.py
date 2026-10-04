"""Source-value regressions that reject convincing but unsupported model output."""
import unittest
from llm import validate_facts


class Grounding(unittest.TestCase):
    def test_swapped_numbers_and_freeform_claims_fail(self):
        evidence = {'case:x': {'total_overdue_cad': '120', 'current_dpd': '30', 'case_status': 'open'}}
        for body in ({'facts': [{'source': 'case:x', 'field': 'current_dpd', 'value': '120'}]},
                     {'facts': [{'text': 'Customer is bankrupt.', 'sources': ['case:x']}]},
                     {'facts': [{'source': 'case:x', 'field': 'permission', 'value': 'call now'}]},
                     {'facts': [{'source': 'case:y', 'field': 'case_status', 'value': 'open'}]}):
            with self.assertRaises(ValueError):
                validate_facts(body, evidence)

    def test_unknown_and_duplicate_fields(self):
        fact = {'source': 'case:x', 'field': 'current_dpd', 'value': None}
        evidence = {'case:x': {'current_dpd': None}}
        self.assertEqual(validate_facts({'facts': [fact]}, evidence)[0]['text'], 'Days past due: unknown.')
        with self.assertRaises(ValueError):
            validate_facts({'facts': [fact, fact]}, evidence)
        with self.assertRaises(ValueError):
            validate_facts({'facts': [{**fact, 'value': '0'}]}, evidence)


if __name__ == '__main__':
    unittest.main()
