"""C's runnable reference baseline: character unigram+bigram BM25, no synonym inference."""
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from src.corpus.annotations import read_work

def tokenize(text):
    normalized = unicodedata.normalize('NFKC', text).lower()
    tokens = []
    for segment in re.findall(r'[\u3400-\u9fff]+|[a-z0-9]+', normalized):
        if re.fullmatch('[a-z0-9]+', segment):
            tokens.append(segment)
        else:
            tokens.extend(segment)
            tokens.extend(segment[i:i+2] for i in range(len(segment)-1))
    return tokens

class BM25Baseline:
    backend = 'character_bigram_bm25_baseline'

    def __init__(self, documents, k1=1.5, b=0.75):
        self.documents = documents
        self.k1, self.b = k1, b
        self.counts = [Counter(tokenize(d['text'])) for d in documents]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.avgdl = sum(self.lengths) / max(1, len(documents)) or 1
        self.df = Counter(t for c in self.counts for t in c)

    def search(self, query, top_k=5, domain=None):
        terms = set(tokenize(query))
        rows = []
        n = len(self.documents)
        for doc, counts, length in zip(self.documents, self.counts, self.lengths):
            if domain and doc['domain'] != domain:
                continue
            score = 0.0
            for term in terms:
                tf = counts.get(term, 0)
                if tf:
                    idf = math.log(1 + (n-self.df[term]+0.5)/(self.df[term]+0.5))
                    score += idf * tf * (self.k1+1) / (tf+self.k1*(1-self.b+self.b*length/self.avgdl))
            if score > 0:
                rows.append({'doc_id': doc['doc_id'], 'score': round(score, 6)})
        return sorted(rows, key=lambda d: (-d['score'], d['doc_id']))[:top_k]

def load_mappings(annotation_dir):
    """讀取 A～E 工作表裡的口語對照，整理成 {口語: [法律詞, ...]}。"""
    mappings = {}
    for role in 'ABCDE':
        path = Path(annotation_dir) / (role + '.csv')
        if not path.exists():
            continue
        for row in read_work(path):
            if row['kind'] != 'mapping':
                continue
            colloquial = row['text'].strip()    # 口語，例如「網購」
            legal_term = row['target'].strip()  # 法律詞，例如「通訊交易」
            if colloquial not in mappings:
                mappings[colloquial] = []
            if legal_term not in mappings[colloquial]:
                mappings[colloquial].append(legal_term)
    return mappings


class MappingExpansionBM25:
    """C 的改良版：先用口語對照表把法律詞補進查詢（W1 p.15 的 query expansion），再交給原本的 BM25 打分。"""
    backend = 'mapping_expansion_bm25'

    def __init__(self, documents, mappings, k1=1.5, b=0.75):
        self.baseline = BM25Baseline(documents, k1, b)  # 打分數完全沿用原版
        self.mappings = mappings                         # {口語: [法律詞, ...]}

    def expand(self, query):
        """找出查詢裡出現的口語詞，回傳要補進查詢的法律詞（不重複）。"""
        added_terms = []
        for colloquial, legal_terms in self.mappings.items():
            if colloquial in query:
                for term in legal_terms:
                    if term not in query and term not in added_terms:
                        added_terms.append(term)
        return added_terms

    def search(self, query, top_k=5, domain=None):
        added_terms = self.expand(query)
        expanded_query = ' '.join([query] + added_terms)
        return self.baseline.search(expanded_query, top_k, domain)