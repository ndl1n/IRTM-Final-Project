"""B: the speed benchmark runs end to end and writes its report (tiny settings, fast)."""
import tempfile
import unittest
from pathlib import Path
from src.services import LawExploreService
from src.phrase_mining.benchmark import run, write_report


class BenchmarkSmokeTest(unittest.TestCase):
    def test_small_run_writes_report(self):
        s = LawExploreService()
        result = run(s.documents, s.phrases[:5], repeats=2, build_repeats=1, per_group=5)
        self.assertTrue(all(r['same_result'] for r in result['queries']))
        self.assertEqual(result['summary'][-1]['group'], 'all')
        self.assertEqual([x['fraction'] for x in result['scaling']], [0.25, 0.5, 0.75, 1.0])
        with tempfile.TemporaryDirectory() as tmp:
            write_report(result, tmp, s.corpus_id)
            for name in ('benchmark.md', 'benchmark.json', 'query_times.csv', 'scaling.csv'):
                self.assertTrue((Path(tmp) / name).stat().st_size > 0, name)


if __name__ == '__main__':
    unittest.main()
