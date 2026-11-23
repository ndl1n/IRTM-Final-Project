"""C 的改良前後比較：用 C.csv 的題目，同時跑原版 BM25 和查詢擴充版，存檔並印出對照。
執行方式（在專案資料夾）：python -m src.retrieval.compare_c
"""
import json
from src.services import LawExploreService, ROOT
from src.corpus.annotations import read_work
from src.retrieval.bm25 import BM25Baseline, MappingExpansionBM25, load_mappings
from src.evaluation.metrics import evaluate

TOP_K = 10  # 取前 10 名，E 算 MRR@10、nDCG@10 需要 10 名

# 1. 準備資料：法條、C 的題目、標準答案
service = LawExploreService()
work = read_work(ROOT / 'data/annotations/C.csv')
queries = [row for row in work if row['kind'] == 'query']
qrels = {}  # {題號: {法條編號: 相關性}}
for row in work:
    if row['kind'] == 'qrel':
        if row['query_id'] not in qrels:
            qrels[row['query_id']] = {}
        qrels[row['query_id']][row['doc_id']] = int(row['label'])

# 2. 建立兩個版本：唯一的差別是有沒有查詢擴充
baseline = BM25Baseline(service.documents)
expanded = MappingExpansionBM25(service.documents, load_mappings(ROOT / 'data/annotations'))

# 3. 每一題都跑兩個版本，記下名次和分數
records = []
baseline_runs = {}  # {題號: [依名次排好的法條編號]}，給 evaluate 用
expanded_runs = {}
for query in queries:
    qid = query['id']
    before = baseline.search(query['text'], TOP_K)
    after = expanded.search(query['text'], TOP_K)
    baseline_runs[qid] = [row['doc_id'] for row in before]
    expanded_runs[qid] = [row['doc_id'] for row in after]
    records.append({
        'query_id': qid,
        'query': query['text'],
        'added_terms': expanded.expand(query['text']),
        'baseline': [{'rank': i, 'doc_id': row['doc_id'], 'score': row['score']} for i, row in enumerate(before, 1)],
        'expanded': [{'rank': i, 'doc_id': row['doc_id'], 'score': row['score']} for i, row in enumerate(after, 1)],
    })

# 4. 存檔（results/ 不會被 Git 上傳，別人照同一個指令就能重跑出來）
output_dir = ROOT / 'results/local'
output_dir.mkdir(parents=True, exist_ok=True)
output = {
    'corpus_id': service.corpus_id,
    'parameters': {'k1': 1.5, 'b': 0.75, 'top_k': TOP_K, 'domain': None},
    'methods': {'baseline': baseline.backend, 'expanded': expanded.backend},
    'runs': records,
}
output_path = output_dir / 'C_compare_run.json'
output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
for variant, method in output['methods'].items():
    run = {
        'corpus_id': service.corpus_id,
        'index_id': service.index_id,
        'method': method,
        'top_k': TOP_K,
        'runs': [
            {'query_id': record['query_id'], 'results': record[variant]}
            for record in records
        ],
    }
    (output_dir / f'C_{variant}_run.json').write_text(
        json.dumps(run, ensure_ascii=False, indent=2), encoding='utf-8')

# 5. 印出對照：每題的標準答案在兩版各排第幾名（10 名外顯示 -）
def rank_of(doc_id, ranked_ids):
    if doc_id in ranked_ids:
        return str(ranked_ids.index(doc_id) + 1)
    return '-'

for record in records:
    qid = record['query_id']
    print(qid, record['query'])
    print('  補上的法律詞:', record['added_terms'])
    for doc_id, label in qrels[qid].items():
        before_rank = rank_of(doc_id, baseline_runs[qid])
        after_rank = rank_of(doc_id, expanded_runs[qid])
        print('  ', doc_id, '相關性', label, '名次', before_rank, '->', after_rank)

# 6. 用 E 的評分程式算整體分數（參考用，正式評估由 E 負責）
before_scores = evaluate(baseline_runs, qrels)['metrics']
after_scores = evaluate(expanded_runs, qrels)['metrics']
print('整體分數（改良前 -> 改良後）')
for name in before_scores:
    print('  ', name, round(before_scores[name], 3), '->', round(after_scores[name], 3))
print('已存檔:', output_path)
