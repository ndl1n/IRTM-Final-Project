"""D: document-level co-occurrence, NOT semantic, causal or legal relations.

Calls return summary rows by default. Request evidence to include original text
and match positions for both phrases in each shared document.
"""
from src.phrase_mining.reference import positions


def related_terms(term, phrase_index, seed_phrases, limit=5, *,
                  include_evidence=False, documents=None, domain=None):
    """Rank literal phrase co-occurrence by Jaccard; deduplicate document IDs.

    Evidence positions are recomputed from the supplied corpus text, not trusted
    blindly from index offsets; a claimed match absent in text raises an error.
    Offsets are Unicode code points, zero-based, end-exclusive. ``domain``
    filters both the numerator and denominator, not merely displayed evidence.
    Existing API remains unfiltered unless callers explicitly opt in.
    """
    if not term:
        raise ValueError('phrase cannot be blank')
    by_id = None
    scope = None
    if include_evidence or domain is not None:
        source = documents if documents is not None else getattr(phrase_index, 'documents', None)
        if source is None:
            raise ValueError('evidence/domain requires source documents')
        by_id = {}
        for doc in source:
            if doc['doc_id'] in by_id and by_id[doc['doc_id']] != doc:
                raise ValueError('conflicting duplicate document: ' + doc['doc_id'])
            by_id[doc['doc_id']] = doc
        if domain is not None and domain not in {d.get('domain') for d in by_id.values()}:
            raise ValueError('unknown domain: ' + str(domain))
        scope = {key for key, doc in by_id.items() if domain is None or doc.get('domain') == domain}

    def lookup_ids(phrase):
        ids = {d['doc_id'] for d in phrase_index.lookup(phrase)['documents']}
        if by_id is not None and not ids <= by_id.keys():
            raise ValueError('index contains documents missing from source')
        return ids if scope is None else ids & scope

    a = lookup_ids(term)
    result = []
    for other in dict.fromkeys(seed_phrases):
        if other == term:
            continue
        b = lookup_ids(other)
        common = a & b
        if common:
            row = {'phrase': other, 'score': len(common)/len(a | b),
                   'cooccurrence_df': len(common), 'method': 'document_jaccard'}
            if include_evidence:
                row.update(term=term, term_df=len(a), phrase_df=len(b), union_df=len(a | b),
                           domain=domain, cooccurrence_doc_ids=sorted(common))
            result.append(row)
    ranked = sorted(result, key=lambda d: (-d['score'], d['phrase']))[:limit]
    if include_evidence:
        for row in ranked:
            row['evidence'] = [
                _evidence(by_id[key], term, row['phrase'])
                for key in row['cooccurrence_doc_ids']
            ]
    return ranked


def _evidence(doc, term, other):
    """Return every literal occurrence, with a context for each (no truncation)."""
    matches = []
    for phrase in (term, other):
        hits = positions(doc['text'], phrase)
        if not hits:
            raise ValueError('index/text mismatch for ' + doc['doc_id'] + ': ' + phrase)
        matches.append({'phrase': phrase, 'positions': hits,
                        'contexts': [context(doc['text'], p['start'], p['end']) for p in hits]})
    return {'doc_id': doc['doc_id'], 'corpus_id': doc.get('corpus_id'),
            'source_url': doc.get('source_url'), 'law_name': doc.get('law_name'),
            'article_no': doc.get('article_no'), 'matches': matches}


def context(text, start, end, window=36):
    left, right = max(0, start-window), min(len(text), end+window)
    return {'text': text[left:right], 'context_start': left,
            'match_start': start-left, 'match_end': end-left}
