"""E: retrieval evaluation — metrics, reproducible runs and A/B comparison.

Library use:   evaluate(runs, qrels)  (unchanged contract, see docs/TECHNICAL.md)
Command line (run from the project root):
    python -X utf8 -m src.evaluation.metrics run --name baseline
    python -X utf8 -m src.evaluation.metrics run --run results/local/baseline_run.json --name saved
    python -X utf8 -m src.evaluation.metrics compare results/eval/before/run.json results/eval/after/run.json
Outputs go to results/eval/<name>/: run.json, per_query.csv, summary.json, report.md.
"""
import csv
import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METRICS = ('MRR@10', 'Recall@5', 'nDCG@10')


def evaluate(runs, qrels):
    """Input maps query IDs to ranked unique doc IDs / {doc_id: graded relevance}.
    Grades 0..2, binary relevance >0 for MRR/Recall; all judged queries averaged.
    No-positive queries are errors, never silently discarded.
    """
    if not qrels:
        raise ValueError('qrels is empty')
    details = []
    if set(runs) - set(qrels):
        raise ValueError('run contains unknown query IDs')
    for qid, judgments in sorted(qrels.items()):
        if any(not isinstance(v, int) or v not in (0,1,2) for v in judgments.values()):
            raise ValueError('relevance must be integer 0, 1 or 2')
        relevant = {d for d,v in judgments.items() if v > 0}
        if not relevant:
            raise ValueError('Query has no positive judgments: ' + qid)
        ranked = runs.get(qid, [])
        if len(ranked) != len(set(ranked)):
            raise ValueError('duplicate document in ranking')
        rr = next((1/i for i,d in enumerate(ranked[:10],1) if d in relevant), 0)
        recall = len(set(ranked[:5]) & relevant)/len(relevant)
        dcg = sum((2**judgments.get(d,0)-1)/math.log2(i+1) for i,d in enumerate(ranked[:10],1))
        ideal = sum((2**v-1)/math.log2(i+1) for i,v in enumerate(sorted(judgments.values(), reverse=True)[:10],1))
        details.append({'query_id': qid, 'MRR@10': rr, 'Recall@5': recall, 'nDCG@10': dcg/ideal})
    return {'query_count': len(details), 'metrics': {k:sum(d[k] for d in details)/len(details) for k in ('MRR@10','Recall@5','nDCG@10')}, 'per_query': details}


# ---------------------------------------------------------------- inputs

def load_judgments(annotation_dir=None, roles='ABCDE', splits=None):
    """Read query/qrel rows from the role CSVs. Returns (queries, qrels).
    queries: {query_id: {'text', 'author', 'split'}}; qrels: {query_id: {doc_id: grade}}.
    Queries without any qrel are skipped (reported by the caller)."""
    from src.corpus.annotations import read_work
    annotation_dir = Path(annotation_dir or ROOT/'data/annotations')
    queries, qrels = {}, {}
    for role in roles:
        path = annotation_dir/(role + '.csv')
        if not path.exists():
            continue
        for r in read_work(path):
            if r['kind'] == 'query' and (not splits or r['label'] in splits):
                queries[r['id']] = {'text': r['text'], 'author': r['author'], 'split': r['label']}
            elif r['kind'] == 'qrel':
                qrels.setdefault(r['query_id'], {})[r['doc_id']] = int(r['label'])
    qrels = {q: j for q, j in qrels.items() if q in queries}
    return queries, qrels


def load_run(path):
    """Accept three formats and return {'meta': {...}, 'runs': {query_id: [doc_id, ...]}}:
    1. `manage.py export` / this tool: {"runs": [{"query_id", "results": [{"doc_id", "rank"}]}]}
    2. plain JSON {query_id: [doc_id, ...]}
    3. CSV with columns query_id, doc_id, rank (C's before/after tables)."""
    path = Path(path)
    if path.suffix.lower() == '.csv':
        rows = {}
        with path.open(encoding='utf-8-sig', newline='') as f:
            for r in csv.DictReader(f):
                rows.setdefault(r['query_id'], []).append((int(r['rank']), r['doc_id']))
        return {'meta': {'source': str(path)}, 'runs': {q: [d for _, d in sorted(v)] for q, v in rows.items()}}
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(data.get('runs'), list):
        runs = {r['query_id']: [x['doc_id'] for x in sorted(r['results'], key=lambda x: x.get('rank', 0))]
                for r in data['runs']}
        meta = {k: v for k, v in data.items() if k != 'runs'}
        return {'meta': meta, 'runs': runs}
    return {'meta': {'source': str(path)}, 'runs': {q: list(v) for q, v in data.items()}}


def live_run(queries, top_k=10, domain=None):
    """Rank every query with the system currently wired in src/services.py."""
    from src.services import LawExploreService
    service = LawExploreService()
    runs = []
    for qid, q in sorted(queries.items()):
        result = service.search(q['text'], top_k, domain)
        runs.append({'query_id': qid, 'query': q['text'],
                     'results': [{k: r[k] for k in ('doc_id', 'rank', 'score')} for r in result['results']]})
    meta = {'corpus_id': service.corpus_id, 'index_id': service.index_id,
            'method': service.retriever.backend, 'top_k': top_k, 'domain_filter': domain}
    return meta, runs


# ---------------------------------------------------------------- diagnostics

def diagnose(ranked, judgments):
    """Explain a single query: where the first relevant doc sits, what was missed."""
    relevant = {d for d, v in judgments.items() if v > 0}
    first = next((i for i, d in enumerate(ranked, 1) if d in relevant), None)
    top10 = ranked[:10]
    return {'first_relevant_rank': first,
            'missed_in_top10': sorted(relevant - set(top10)),
            'judged_at_10': (sum(d in judgments for d in top10) / len(top10)) if top10 else 0.0,
            'top3': ranked[:3]}


def score_run(runs, qrels, queries):
    report = evaluate({q: r for q, r in runs.items() if q in qrels}, qrels)
    rows = []
    for d in report['per_query']:
        qid = d['query_id']
        row = dict(d, query=queries[qid]['text'], author=queries[qid]['author'], split=queries[qid]['split'],
                   **diagnose(runs.get(qid, []), qrels[qid]))
        rows.append(row)
    groups = {}
    for r in rows:
        groups.setdefault(r['author'], []).append(r)
    by_author = {a: {'query_count': len(g), **{m: mean([r[m] for r in g]) for m in METRICS}}
                 for a, g in sorted(groups.items())}
    judged = mean([r['judged_at_10'] for r in rows])
    return {'query_count': len(rows), 'metrics': report['metrics'], 'by_author': by_author,
            'mean_judged_at_10': judged, 'per_query': rows}


# ---------------------------------------------------------------- statistics

def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def paired_tests(a, b, iterations=10000, seed=13):
    """Two-sided paired randomization (sign-flip) test and bootstrap 95% CI for mean(b - a).
    Fixed seed so the numbers in the report can be rerun exactly."""
    diffs = [y - x for x, y in zip(a, b)]
    n = len(diffs)
    observed = mean(diffs)
    rng = random.Random(seed)
    if n <= 16:  # exact: enumerate every sign assignment
        total = 1 << n
        extreme = sum(abs(sum(d if (mask >> i) & 1 else -d for i, d in enumerate(diffs))) / n >= abs(observed) - 1e-12
                      for mask in range(total))
        p = extreme / total
        method = 'exact sign-flip'
    else:
        extreme = sum(abs(mean([d if rng.random() < .5 else -d for d in diffs])) >= abs(observed) - 1e-12
                      for _ in range(iterations))
        p = (extreme + 1) / (iterations + 1)
        method = 'sign-flip, %d samples' % iterations
    boots = sorted(mean([diffs[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations))
    ci = (boots[int(.025 * iterations)], boots[int(.975 * iterations) - 1])
    return {'mean_diff': observed, 'p_value': p, 'ci95': ci, 'test': method,
            'wins': sum(d > 1e-12 for d in diffs), 'losses': sum(d < -1e-12 for d in diffs),
            'ties': sum(abs(d) <= 1e-12 for d in diffs)}


def compare(runs_a, runs_b, qrels, queries):
    sa, sb = score_run(runs_a, qrels, queries), score_run(runs_b, qrels, queries)
    pa = {r['query_id']: r for r in sa['per_query']}
    pb = {r['query_id']: r for r in sb['per_query']}
    qids = sorted(pa)
    tests = {m: paired_tests([pa[q][m] for q in qids], [pb[q][m] for q in qids]) for m in METRICS}
    per_query = [{'query_id': q, 'query': pa[q]['query'],
                  **{m + '_a': pa[q][m] for m in METRICS}, **{m + '_b': pb[q][m] for m in METRICS},
                  'delta_nDCG@10': pb[q]['nDCG@10'] - pa[q]['nDCG@10'],
                  'first_rel_a': pa[q]['first_relevant_rank'], 'first_rel_b': pb[q]['first_relevant_rank']}
                 for q in qids]
    per_query.sort(key=lambda r: -r['delta_nDCG@10'])
    return {'a': sa, 'b': sb, 'tests': tests, 'per_query': per_query}


# ---------------------------------------------------------------- outputs

def fmt(x):
    return '—' if x is None else ('%.3f' % x if isinstance(x, float) else str(x))


def write_csv(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in r.items()})


def render_report(name, meta, scored, skipped):
    m = scored['metrics']
    lines = ['# 評估報告：%s' % name, '',
             '- 語料 `%s`，索引 `%s`，方法 `%s`' % (meta.get('corpus_id'), meta.get('index_id'), meta.get('method', meta.get('source'))),
             '- 題數 %d（未附相關性標註而略過：%s）' % (scored['query_count'], ', '.join(skipped) or '無'),
             '- 前 10 名中有標註的比例平均 %.0f%%；未標註文件一律算不相關，分數可能偏低。' % (100 * scored['mean_judged_at_10']),
             '', '| 範圍 | 題數 | MRR@10 | Recall@5 | nDCG@10 |', '|---|---|---|---|---|',
             '| **全部** | %d | %s |' % (scored['query_count'], ' | '.join(fmt(m[k]) for k in METRICS))]
    for a, g in scored['by_author'].items():
        lines.append('| %s | %d | %s |' % (a, g['query_count'], ' | '.join(fmt(g[k]) for k in METRICS)))
    lines += ['', '## 每題結果（依 nDCG@10 由低到高）', '',
              '| 題號 | 問題 | MRR@10 | Recall@5 | nDCG@10 | 第一筆相關名次 | 前 10 未找回 |', '|---|---|---|---|---|---|---|']
    for r in sorted(scored['per_query'], key=lambda r: (r['nDCG@10'], r['query_id'])):
        lines.append('| %s | %s | %s | %s | %s | %s | %s |' % (
            r['query_id'], r['query'], fmt(r['MRR@10']), fmt(r['Recall@5']), fmt(r['nDCG@10']),
            fmt(r['first_relevant_rank']), ', '.join(x.replace('moj_', '') for x in r['missed_in_top10']) or '—'))
    return '\n'.join(lines) + '\n'


def render_compare(name, cmp_):
    lines = ['# A/B 比較：%s' % name, '', '同一批題目與標註；檢定為配對 sign-flip 檢定，CI 為 bootstrap 95%（固定亂數種子 13）。', '',
             '| 指標 | A | B | B−A | 95% CI | p 值 | 進步/退步/持平 |', '|---|---|---|---|---|---|---|']
    for m in METRICS:
        t = cmp_['tests'][m]
        lines.append('| %s | %s | %s | %+.3f | [%+.3f, %+.3f] | %.3f | %d / %d / %d |' % (
            m, fmt(cmp_['a']['metrics'][m]), fmt(cmp_['b']['metrics'][m]), t['mean_diff'],
            t['ci95'][0], t['ci95'][1], t['p_value'], t['wins'], t['losses'], t['ties']))
    lines += ['', '題數少時 p 值只能當參考；報告請同時寫出進步與退步的具體題目。', '',
              '## 每題變化（依 nDCG@10 變化排序）', '',
              '| 題號 | 問題 | nDCG A | nDCG B | 變化 | 第一筆相關名次 A→B |', '|---|---|---|---|---|---|']
    for r in cmp_['per_query']:
        lines.append('| %s | %s | %s | %s | %+.3f | %s → %s |' % (
            r['query_id'], r['query'], fmt(r['nDCG@10_a']), fmt(r['nDCG@10_b']), r['delta_nDCG@10'],
            fmt(r['first_rel_a']), fmt(r['first_rel_b'])))
    return '\n'.join(lines) + '\n'


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog='python -m src.evaluation.metrics')
    sub = parser.add_subparsers(dest='command', required=True)
    for cmd in ('run', 'compare'):
        p = sub.add_parser(cmd)
        p.add_argument('--roles', default='ABCDE', help='Which role CSVs supply queries/qrels, e.g. AE')
        p.add_argument('--splits', default='', help='Comma list of query labels to keep, e.g. development,demo')
        p.add_argument('--name', default=None)
        p.add_argument('--out', default=str(ROOT/'results/eval'))
    run_p = sub.choices['run']
    run_p.add_argument('--run', help='Saved run file; omit to rank live with the current system')
    run_p.add_argument('--top-k', type=int, default=10)
    run_p.add_argument('--domain', default=None)
    cmp_p = sub.choices['compare']
    cmp_p.add_argument('run_a')
    cmp_p.add_argument('run_b')
    args = parser.parse_args(argv)

    splits = {s for s in args.splits.split(',') if s}
    queries, qrels = load_judgments(roles=args.roles, splits=splits)
    skipped = sorted(set(queries) - set(qrels))
    queries = {q: v for q, v in queries.items() if q in qrels}
    if not queries:
        raise SystemExit('No queries with judgments for roles=%s splits=%s' % (args.roles, args.splits))

    if args.command == 'run':
        if args.run:
            loaded = load_run(args.run)
            meta, runs = loaded['meta'], loaded['runs']
            raw = None
        else:
            meta, raw = live_run(queries, args.top_k, args.domain)
            runs = {r['query_id']: [x['doc_id'] for x in r['results']] for r in raw}
        missing = sorted(set(queries) - set(runs))
        scored = score_run(runs, qrels, queries)
        name = args.name or ('live' if not args.run else Path(args.run).stem)
        out = Path(args.out)/name
        out.mkdir(parents=True, exist_ok=True)
        meta = dict(meta, roles=args.roles, splits=sorted(splits), queries_without_ranking=missing)
        if raw is not None:
            (out/'run.json').write_text(json.dumps(dict(meta, runs=raw), ensure_ascii=False, indent=2), encoding='utf-8')
        (out/'summary.json').write_text(json.dumps(dict(meta=meta, **scored), ensure_ascii=False, indent=2), encoding='utf-8')
        write_csv(out/'per_query.csv', scored['per_query'])
        (out/'report.md').write_text(render_report(name, meta, scored, skipped), encoding='utf-8')
        print(json.dumps({'output': str(out), 'query_count': scored['query_count'],
                          'metrics': {k: round(v, 4) for k, v in scored['metrics'].items()},
                          'queries_without_ranking': missing}, ensure_ascii=False))
    else:
        a, b = load_run(args.run_a), load_run(args.run_b)
        for key in ('corpus_id',):
            if a['meta'].get(key) and b['meta'].get(key) and a['meta'][key] != b['meta'][key]:
                raise SystemExit('Runs use different %s; compare on the same corpus.' % key)
        cmp_ = compare(a['runs'], b['runs'], qrels, queries)
        name = args.name or '%s_vs_%s' % (Path(args.run_a).parent.name, Path(args.run_b).parent.name)
        out = Path(args.out)/name
        out.mkdir(parents=True, exist_ok=True)
        (out/'compare.json').write_text(json.dumps(cmp_, ensure_ascii=False, indent=2), encoding='utf-8')
        write_csv(out/'per_query_delta.csv', cmp_['per_query'])
        (out/'report.md').write_text(render_compare(name, cmp_), encoding='utf-8')
        print(json.dumps({'output': str(out), **{m: {k: cmp_['tests'][m][k] for k in ('mean_diff', 'p_value', 'wins', 'losses')}
                                               for m in METRICS}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
