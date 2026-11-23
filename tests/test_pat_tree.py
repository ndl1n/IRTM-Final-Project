"""B: PAT-tree must return exactly what the reference scanner returns."""
import random
import unittest
from src.services import LawExploreService
from src.phrase_mining.pat_tree import PATTreeIndex
from src.phrase_mining.reference import ReferencePhraseIndex


def strip_backend(result):
    return {k: v for k, v in result.items() if k != 'backend'}


class PATTreeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = LawExploreService().documents
        cls.pat = PATTreeIndex(cls.docs)
        cls.ref = ReferencePhraseIndex(cls.docs)

    def assertParity(self, phrase, pat=None, ref=None):
        pat, ref = pat or self.pat, ref or self.ref
        self.assertEqual(strip_backend(pat.lookup(phrase)), strip_backend(ref.lookup(phrase)), phrase)

    def test_seed_and_labour_phrases(self):
        for phrase in ['工作時間', '延長工作時間', '工資', '雇主', '勞工', '押金', '點交', '修繕',
                       '個人資料', '蒐集', '第', '，', '。', '不存在的詞組']:
            self.assertParity(phrase)

    def test_random_substrings_of_corpus(self):
        rng = random.Random(20261119)
        for _ in range(500):
            text = rng.choice(self.docs)['text']
            start = rng.randrange(len(text))
            phrase = text[start:start + rng.randint(1, 12)]
            self.assertParity(phrase)

    def test_overlap_unicode_and_document_boundary(self):
        docs = [{'doc_id': 'a', 'text': '哈哈哈出租'}, {'doc_id': 'b', 'text': '人😀修繕哈哈'}]
        pat, ref = PATTreeIndex(docs), ReferencePhraseIndex(docs)
        for phrase in ['哈哈', '哈', '出租人', '租人', '修繕', '😀修', '哈哈哈哈', 'x']:
            self.assertParity(phrase, pat, ref)
        self.assertEqual(pat.lookup('哈哈')['documents'][0]['positions'],
                         [{'start': 0, 'end': 2}, {'start': 1, 'end': 3}])
        self.assertEqual(pat.lookup('出租人')['frequency'], 0)

    def test_blank_phrase_rejected(self):
        with self.assertRaises(ValueError):
            self.pat.lookup('')


if __name__ == '__main__':
    unittest.main()
