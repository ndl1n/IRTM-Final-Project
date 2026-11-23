"""Composition root: replace module constructors HERE, keep transport/UI contracts stable."""
import hashlib
import json
from pathlib import Path
from src.corpus.validation import load_corpus
from src.phrase_mining.pat_tree import PATTreeIndex
from src.retrieval.bm25 import BM25Baseline
from src.retrieval.recommender import suggest
from src.relation_mining.relations import context, related_terms

ROOT = Path(__file__).resolve().parents[1]

class ServiceError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)

class LawExploreService:
    def __init__(self, root=ROOT):
        self.root = root
        self.config = json.loads((root/'config/project.json').read_text(encoding='utf-8'))
        self.corpus_id = self.config['corpus_id']
        path = root/self.config['corpus_path']
        self.documents = load_corpus(path, self.corpus_id)
        self.by_id = {d['doc_id']: d for d in self.documents}
        self.phrases = json.loads((root/self.config['phrase_path']).read_text(encoding='utf-8'))
        # B: PAT-tree, parity with ReferencePhraseIndex checked in tests/test_pat_tree.py.
        self.phrase_index = PATTreeIndex(self.documents)
        # C replaces or improves this baseline after recording a reproducible comparison.
        self.retriever = BM25Baseline(self.documents)
        self.index_id = 'starter-' + hashlib.sha256(path.read_bytes()).hexdigest()[:12]

    def check_corpus(self, corpus_id):
        if corpus_id != self.corpus_id:
            raise ServiceError(404, 'unknown_corpus', '找不到這個語料版本；不可混用 Benchmark ID。')

    def validate_term(self, value):
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ServiceError(400, 'invalid_query', '請輸入 1～200 字的查詢。')
        return value.strip()

    def metadata(self):
        domains = sorted({d['domain'] for d in self.documents})
        return {'corpus_id': self.corpus_id, 'index_id': self.index_id,
                'document_count': len(self.documents),
                'law_count': len({d['law_id'] for d in self.documents
                                  if d.get('document_type') != 'contract_rule'}),
                'domains': domains, 'search_backend': self.retriever.backend,
                'phrase_backend': self.phrase_index.backend, 'seed_phrases': self.phrases,
                'status': 'starter', 'source_status': 'official_snapshot_effectivity_pending_review',
                'logging_enabled': self.config['logging_enabled'],
                'domain_counts': {name:sum(d['domain']==name for d in self.documents) for name in domains}}

    def document(self, doc_id):
        if doc_id not in self.by_id:
            raise ServiceError(404, 'unknown_document', '找不到這筆法條。')
        return self.by_id[doc_id]

    def search(self, query, top_k=5, domain=None):
        query = self.validate_term(query)
        if not isinstance(top_k, int) or not 1 <= top_k <= 20:
            raise ServiceError(400, 'invalid_top_k', 'top_k 必須是 1～20 的整數。')
        if domain and domain not in {d['domain'] for d in self.documents}:
            raise ServiceError(400, 'invalid_domain', '未知的領域。')
        ranked = self.retriever.search(query, top_k, domain)
        documents = [self.by_id[r['doc_id']] for r in ranked]
        results = []
        for rank, (row, doc) in enumerate(zip(ranked, documents), 1):
            results.append(dict(doc_id=doc['doc_id'], rank=rank, score=row['score'],
                                law_name=doc['law_name'], article_no=doc['article_no'], domain=doc['domain'],
                                snippet=doc['text'][:220], source_url=doc['source_url'],
                                matched_phrases=[p for p in self.phrases if p in query and p in doc['text']]))
        return {'query': query, 'corpus_id': self.corpus_id, 'index_id': self.index_id,
                'method': self.retriever.backend, 'results': results,
                'suggestions': suggest(query, documents, self.phrases)}

    def phrase(self, term):
        term = self.validate_term(term)
        result = self.phrase_index.lookup(term)
        for match in result['documents']:
            doc = self.by_id[match['doc_id']]
            match.update(law_name=doc['law_name'], article_no=doc['article_no'], source_url=doc['source_url'])
            match['contexts'] = [context(doc['text'], p['start'], p['end']) for p in match['positions'][:3]]
        result.update(corpus_id=self.corpus_id, index_id=self.index_id,
                      related_terms=related_terms(term, self.phrase_index, self.phrases))
        return result
