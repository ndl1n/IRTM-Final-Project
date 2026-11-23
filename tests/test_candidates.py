"""B: candidate phrases come from the PAT-tree and must map back to the original text."""
import unittest
from src.services import LawExploreService
from src.phrase_mining.candidates import mine, NUMBERING, CJK_ONLY, STRUCTURAL
from src.phrase_mining.pat_tree import PATTreeIndex
from src.phrase_mining.reference import ReferencePhraseIndex


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = LawExploreService()
        cls.index = PATTreeIndex(cls.s.documents)
        cls.ref = ReferencePhraseIndex(cls.s.documents)
        cls.labour = mine(cls.s.documents, cls.index, domain='勞動')

    def test_found_without_seeds(self):
        phrases = {r['phrase'] for r in self.labour}
        for expected in ['工作時間', '延長工作時間', '勞動契約', '特別休假', '資遣費', '平均工資']:
            self.assertIn(expected, phrases)
        self.assertNotIn('作時間', phrases)        # 左邊永遠是「工」，不完整

    def test_two_char_words_recovered_by_pmi(self):
        phrases = {r['phrase'] for r in self.labour}
        for expected in ['例假', '童工', '女工', '工資', '休假', '雇主', '勞工']:
            self.assertIn(expected, phrases)
        for junk in ['條第', '前項', '本法', '依第', '當日', '期內']:   # PMI 規則不可放進的字串
            self.assertNotIn(junk, phrases)

    def test_fragments_subsumed(self):
        phrases = {r['phrase'] for r in self.labour}
        self.assertNotIn('正常工作時', phrases)     # 79% 是「正常工作時間」
        self.assertIn('正常工作時間', phrases)
        self.assertNotIn('有左列情', phrases)
        self.assertIn('勞資會議', phrases)          # 後面常接「同意」，但「勞資會議同」不是候選，不刪
        off = mine(self.s.documents, self.index, domain='勞動', subsume_ratio=0)
        self.assertIn('正常工作時', {r['phrase'] for r in off})

    def test_domain_idf_pushes_generic_words_down(self):
        top20 = [r['phrase'] for r in self.labour[:20]]
        for generic in ['主管機關', '契約', '違反', '機關', '新臺幣']:
            self.assertNotIn(generic, top20)
        rank = {r['phrase']: i for i, r in enumerate(self.labour)}
        self.assertLess(rank['事業單位'], rank['主管機關'])

    def test_counts_and_positions_match_scanner(self):
        for r in self.labour[:60]:
            ref = self.ref.lookup(r['phrase'])
            self.assertEqual(r['frequency'], ref['frequency'], r['phrase'])
            self.assertEqual(r['df'], ref['df'], r['phrase'])
            self.assertEqual(self.index.count(r['phrase']), ref['frequency'])
            for d, o in r['_occurrences']:
                self.assertEqual(self.index.texts[d][o:o + len(r['phrase'])], r['phrase'])

    def test_filters(self):
        for r in self.labour:
            self.assertTrue(CJK_ONLY.match(r['phrase']), r['phrase'])
            self.assertIsNone(NUMBERING.search(r['phrase']), r['phrase'])
            self.assertGreaterEqual(r['domain_df'], 2)
            if r['length'] > 2:
                self.assertGreaterEqual(r['se'], 0.3, r['phrase'])
            elif r['se'] < 0.3:                     # 兩字詞走 PMI 規則
                self.assertGreaterEqual(r['pmi'], 5.0, r['phrase'])
                self.assertEqual(len(r['domains'].split(';')), 1, r['phrase'])
                self.assertFalse(set(r['phrase']) & STRUCTURAL, r['phrase'])

    def test_document_boundary(self):
        docs = [{'doc_id': 'a', 'domain': 'x', 'text': '甲乙丙勞動契約'},
                {'doc_id': 'b', 'domain': 'x', 'text': '終止勞動契約丁'},
                {'doc_id': 'c', 'domain': 'x', 'text': '依勞動契約。'}]
        rows = mine(docs, min_freq=2)
        self.assertIn('勞動契約', {r['phrase'] for r in rows})
        self.assertNotIn('約終', {r['phrase'] for r in rows})


if __name__ == '__main__':
    unittest.main()
