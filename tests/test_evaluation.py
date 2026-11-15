"""E: tests for the evaluation CLI helpers (metrics.evaluate itself is covered in test_core)."""
import json
import tempfile
import unittest
from pathlib import Path
from src.evaluation.metrics import compare, diagnose, load_judgments, load_run, paired_tests, score_run


class EvaluationToolTests(unittest.TestCase):
    def test_load_run_formats_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp/'export.json').write_text(json.dumps({'corpus_id': 'c', 'runs': [
                {'query_id': 'q', 'results': [{'doc_id': 'b', 'rank': 2}, {'doc_id': 'a', 'rank': 1}]}]}), encoding='utf-8')
            (tmp/'plain.json').write_text(json.dumps({'q': ['a', 'b']}), encoding='utf-8')
            (tmp/'table.csv').write_text('query_id,doc_id,rank,score\nq,b,2,1\nq,a,1,2\n', encoding='utf-8')
            runs = [load_run(tmp/n)['runs'] for n in ('export.json', 'plain.json', 'table.csv')]
            self.assertTrue(all(r == {'q': ['a', 'b']} for r in runs))
            self.assertEqual(load_run(tmp/'export.json')['meta']['corpus_id'], 'c')

    def test_diagnose_and_judged_rate(self):
        d = diagnose(['x', 'a', 'y'], {'a': 2, 'b': 1, 'y': 0})
        self.assertEqual(d['first_relevant_rank'], 2)
        self.assertEqual(d['missed_in_top10'], ['b'])
        self.assertAlmostEqual(d['judged_at_10'], 2/3)

    def test_paired_tests_exact(self):
        t = paired_tests([0, 0, 0], [1, 1, 1])
        self.assertEqual((t['wins'], t['losses'], t['ties']), (3, 0, 0))
        self.assertAlmostEqual(t['p_value'], 2/8)  # only all-plus and all-minus are as extreme
        self.assertEqual(paired_tests([.5, .5], [.5, .5])['p_value'], 1.0)

    def test_compare_identical_runs_is_flat(self):
        queries = {'q1': {'text': 't', 'author': 'E', 'split': 'development'},
                   'q2': {'text': 'u', 'author': 'E', 'split': 'development'}}
        qrels = {'q1': {'a': 2}, 'q2': {'b': 1}}
        runs = {'q1': ['a'], 'q2': ['x', 'b']}
        result = compare(runs, runs, qrels, queries)
        self.assertTrue(all(abs(r['delta_nDCG@10']) < 1e-12 for r in result['per_query']))
        self.assertEqual(score_run(runs, qrels, queries)['by_author']['E']['query_count'], 2)

    def test_project_judgments_link_by_id(self):
        queries, qrels = load_judgments(roles='AE')
        self.assertTrue(qrels)
        self.assertTrue(set(qrels) <= set(queries))
        self.assertTrue(all(any(v > 0 for v in j.values()) for j in qrels.values()))


if __name__ == '__main__':
    unittest.main()
