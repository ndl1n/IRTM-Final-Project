"""B: 比較「逐份掃描」(ReferencePhraseIndex) 與 PAT-tree (PATTreeIndex) 的速度。

量四件事：
1. 建索引時間：PAT-tree 要先建樹；掃描版不用建，但每次查詢都要讀完整份語料。
2. 查詢時間：分成五組詞組（種子詞、自動擷取的勞動詞組、隨機抽的原文片段、
   長詞、查無結果），每個詞組重複查 repeats 次取中位數。
3. 損益平衡點：查幾次之後，PAT-tree 省下的時間就能抵掉建樹時間。
4. 語料大小的影響：用 25%／50%／75%／100% 的語料各量一次，
   看掃描版是否隨語料變慢、PAT-tree 是否幾乎不變。

每個詞組也會核對兩邊回傳結果相同，確保比的是「做同一件事」的速度。

可重跑：python -X utf8 -m src.phrase_mining.benchmark
輸出：results/B/benchmark/ 下的 benchmark.md、query_times.csv、scaling.csv、benchmark.json
"""
import argparse
import csv
import json
import platform
import random
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

from src.phrase_mining.candidates import mine
from src.phrase_mining.pat_tree import PATTreeIndex
from src.phrase_mining.reference import ReferencePhraseIndex

NOT_FOUND = ['勞工退休金請領資格查詢', '加班費計算機', '外送員', '居家辦公', '遠距工作',
             '颱風假', '年終獎金', '試用期', '責任制', '勞資爭議調解']


def strip_backend(result):
    return {k: v for k, v in result.items() if k != 'backend'}


def time_lookup(index, phrase, repeats):
    """查同一個詞組 repeats 次，回傳每次耗時的中位數（微秒）。"""
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter_ns()
        index.lookup(phrase)
        samples.append(time.perf_counter_ns() - t0)
    return statistics.median(samples) / 1000


def time_build(documents, repeats):
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        index = PATTreeIndex(documents)
        samples.append(time.perf_counter() - t0)
    return statistics.median(samples), index


def build_memory_mb(documents):
    tracemalloc.start()
    PATTreeIndex(documents)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 1024 / 1024


def phrase_groups(documents, seeds, pat, rng, per_group):
    texts = [d['text'] for d in documents]
    def random_substrings(length):
        out = []
        while len(out) < per_group:
            text = rng.choice(texts)
            if len(text) >= length:
                start = rng.randrange(len(text) - length + 1)
                out.append(text[start:start + length])
        return out
    labour = [r['phrase'] for r in mine(documents, pat, domain='勞動')][:per_group]
    return {
        'seed': list(seeds),
        'mined_labour': labour,
        'random_2char': random_substrings(2),
        'random_8char': random_substrings(8),
        'not_found': NOT_FOUND,
    }


def run(documents, seeds, repeats=20, build_repeats=5, per_group=50, seed=20261121):
    rng = random.Random(seed)
    scan = ReferencePhraseIndex(documents)
    build_s, pat = time_build(documents, build_repeats)
    groups = phrase_groups(documents, seeds, pat, rng, per_group)

    rows = []
    for group, phrases in groups.items():
        for phrase in phrases:
            same = strip_backend(scan.lookup(phrase)) == strip_backend(pat.lookup(phrase))
            if not same:
                raise AssertionError('PAT-tree 與掃描版結果不同：%r' % phrase)
            rows.append({'group': group, 'phrase': phrase, 'length': len(phrase),
                         'frequency': pat.count(phrase),
                         'scan_us': round(time_lookup(scan, phrase, repeats), 2),
                         'pat_tree_us': round(time_lookup(pat, phrase, repeats), 2),
                         'same_result': same})
    for r in rows:
        r['speedup'] = round(r['scan_us'] / r['pat_tree_us'], 1) if r['pat_tree_us'] else ''

    summary = []
    for group in list(groups) + ['all']:
        sel = [r for r in rows if group == 'all' or r['group'] == group]
        scan_avg = statistics.mean(r['scan_us'] for r in sel)
        pat_avg = statistics.mean(r['pat_tree_us'] for r in sel)
        summary.append({'group': group, 'phrases': len(sel),
                        'avg_frequency': round(statistics.mean(r['frequency'] for r in sel), 1),
                        'scan_avg_us': round(scan_avg, 2), 'pat_tree_avg_us': round(pat_avg, 2),
                        'speedup': round(scan_avg / pat_avg, 1)})
    overall = summary[-1]
    saved_us = overall['scan_avg_us'] - overall['pat_tree_avg_us']
    break_even = int(build_s * 1e6 / saved_us) + 1 if saved_us > 0 else None

    # 語料大小的影響：固定一組詞組，換不同大小的語料
    scaling = []
    found, missing = groups['seed'], groups['not_found']
    order = list(range(len(documents)))
    random.Random(seed).shuffle(order)
    for fraction in (0.25, 0.5, 0.75, 1.0):
        subset = [documents[i] for i in sorted(order[:max(1, int(len(documents) * fraction))])]
        sub_scan = ReferencePhraseIndex(subset)
        sub_build, sub_pat = time_build(subset, max(1, build_repeats // 2))
        scaling.append({'fraction': fraction, 'documents': len(subset),
                        'characters': sum(len(d['text']) for d in subset),
                        'pat_tree_nodes': sub_pat.node_count,
                        'build_s': round(sub_build, 4),
                        'seed_avg_hits': round(statistics.mean(sub_pat.count(p) for p in found), 1),
                        'seed_scan_us': round(statistics.mean(time_lookup(sub_scan, p, repeats) for p in found), 2),
                        'seed_pat_tree_us': round(statistics.mean(time_lookup(sub_pat, p, repeats) for p in found), 2),
                        'not_found_scan_us': round(statistics.mean(time_lookup(sub_scan, p, repeats) for p in missing), 2),
                        'not_found_pat_tree_us': round(statistics.mean(time_lookup(sub_pat, p, repeats) for p in missing), 2)})

    return {
        'environment': {'python': sys.version.split()[0], 'platform': platform.platform(),
                        'processor': platform.processor() or platform.machine()},
        'parameters': {'repeats': repeats, 'build_repeats': build_repeats,
                       'phrases_per_group': per_group, 'random_seed': seed},
        'corpus': {'documents': len(documents), 'characters': sum(len(d['text']) for d in documents),
                   'pat_tree_nodes': pat.node_count},
        'build': {'pat_tree_build_s': round(build_s, 4), 'pat_tree_peak_memory_mb': round(build_memory_mb(documents), 1),
                  'scan_build_s': 0.0, 'break_even_queries': break_even},
        'summary': summary, 'scaling': scaling, 'queries': rows,
    }


GROUP_NAMES = {'seed': '種子詞（組員手列）', 'mined_labour': '自動擷取的勞動詞組',
               'random_2char': '隨機原文片段（2 字）', 'random_8char': '隨機原文片段（8 字）',
               'not_found': '查無結果', 'all': '全部'}


def write_report(result, out_dir, corpus_id):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'benchmark.json').write_text(json.dumps({'corpus_id': corpus_id, **result},
                                                       ensure_ascii=False, indent=2), encoding='utf-8')
    with open(out_dir / 'query_times.csv', 'w', encoding='utf-8-sig', newline='') as fp:
        w = csv.DictWriter(fp, ['group', 'phrase', 'length', 'frequency', 'scan_us', 'pat_tree_us', 'speedup', 'same_result'])
        w.writeheader()
        w.writerows(result['queries'])
    with open(out_dir / 'scaling.csv', 'w', encoding='utf-8-sig', newline='') as fp:
        w = csv.DictWriter(fp, list(result['scaling'][0]))
        w.writeheader()
        w.writerows(result['scaling'])

    b, c, p = result['build'], result['corpus'], result['parameters']
    lines = [
        '# PAT-tree 與逐份掃描的速度比較', '',
        '- 語料：`%s`，%d 份文件、%d 字，PAT-tree 共 %d 個節點'
        % (corpus_id, c['documents'], c['characters'], c['pat_tree_nodes']),
        '- 環境：Python %s，%s' % (result['environment']['python'], result['environment']['platform']),
        '- 方法：每個詞組查 %d 次取中位數；建樹 %d 次取中位數；每個詞組都先核對兩邊結果相同'
        % (p['repeats'], p['build_repeats']), '',
        '## 建索引', '',
        '| 項目 | 結果 |', '|---|---|',
        '| PAT-tree 建樹時間 | %.3f 秒 |' % b['pat_tree_build_s'],
        '| PAT-tree 建樹記憶體高峰 | %.1f MB |' % b['pat_tree_peak_memory_mb'],
        '| 逐份掃描 | 不用建索引 |',
        '| 損益平衡點 | 查詢約 %s 次後，PAT-tree 省下的時間超過建樹時間 |' % b['break_even_queries'], '',
        '## 查詢時間（平均每次，微秒；1 毫秒 = 1000 微秒）', '',
        '| 詞組類型 | 詞組數 | 平均出現次數 | 逐份掃描 | PAT-tree | 快幾倍 |', '|---|---|---|---|---|---|',
    ]
    for s in result['summary']:
        lines.append('| %s | %d | %s | %.1f | %.1f | %.1f× |' % (GROUP_NAMES[s['group']], s['phrases'],
                     s['avg_frequency'], s['scan_avg_us'], s['pat_tree_avg_us'], s['speedup']))
    lines += ['', '## 語料大小的影響（單位：微秒）', '',
              '有命中＝36 個種子詞；查無結果＝10 個語料裡沒有的詞。', '',
              '| 語料比例 | 字數 | 建樹秒數 | 種子詞平均命中數 | 有命中：掃描 | 有命中：PAT-tree | 查無結果：掃描 | 查無結果：PAT-tree |',
              '|---|---|---|---|---|---|---|---|']
    for s in result['scaling']:
        lines.append('| %d%% | %d | %.3f | %.1f | %.1f | %.1f | %.1f | %.1f |' % (s['fraction'] * 100,
                     s['characters'], s['build_s'], s['seed_avg_hits'], s['seed_scan_us'], s['seed_pat_tree_us'],
                     s['not_found_scan_us'], s['not_found_pat_tree_us']))
    lines += ['', '## 怎麼解讀', '',
              '- 逐份掃描的時間跟「語料有多大」成正比：每次都要讀完整份語料，查無結果也一樣慢。',
              '- PAT-tree 的時間跟「命中幾次」成正比：先沿著詞組的字走到節點（只走幾步），'
              '再把底下的命中位置收集出來。查無結果時走幾步就停，不論語料多大都約 1 微秒。',
              '- 語料變大時種子詞的命中數也變多，所以 PAT-tree 的「有命中」時間也跟著增加；'
              '但它增加的是「要回傳的結果」，掃描版增加的是「要讀的字」。',
              '- 命中很多次的短詞（例如 2 字片段）差距較小；長詞、少見詞、查無結果的差距最大。',
              '- 代價是建樹時間與記憶體，只要網站啟動時建一次，之後每次查詢都受益。',
              '- 數字會隨電腦不同而變，比較時看倍數與趨勢，不看絕對值。', '']
    (out_dir / 'benchmark.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    from src.services import LawExploreService
    ap = argparse.ArgumentParser(description='比較逐份掃描與 PAT-tree 的速度')
    ap.add_argument('--repeats', type=int, default=20)
    ap.add_argument('--build-repeats', type=int, default=5)
    ap.add_argument('--per-group', type=int, default=50)
    ap.add_argument('--out', default='results/B/benchmark')
    args = ap.parse_args()
    service = LawExploreService()
    result = run(service.documents, service.phrases, args.repeats, args.build_repeats, args.per_group)
    write_report(result, args.out, service.corpus_id)
    print((Path(args.out) / 'benchmark.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    main()
