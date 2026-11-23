"""Shared checker for one CSV per role. Checks structure, never legal correctness."""
import csv
from pathlib import Path

FIELDS=['kind','id','corpus_id','doc_id','query_id','text','target','label','evidence','source_url','author']
KINDS={'audit','phrase','mapping','query','qrel'}

def read_work(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames!=FIELDS:
            raise ValueError(f'{path}: header must match the shared {len(FIELDS)} columns')
        rows = [row for row in reader if any(row.values())]
        for row in rows:
            # Git on Windows can change line endings inside quoted CSV fields.
            if row.get('text') is not None:
                row['text'] = row['text'].replace('\r\n', '\n')
        return rows

def validate_annotations(directory, documents, corpus_id):
    docs={d['doc_id']:d for d in documents};rows=[];queries={};ids=set();pairs=set();errors=[]
    for role in 'ABCDE':
        path=Path(directory)/(role+'.csv')
        if not path.exists():continue
        for line,r in enumerate(read_work(path),2):
            where='%s:%s'%(path.name,line)
            def fail(message):errors.append(where+': '+message)
            rows.append(r)
            if r['kind'] not in KINDS:fail('unknown kind')
            if not r['id'].startswith(role+'_') or r['id'] in ids:fail('invalid/duplicate record id')
            ids.add(r['id'])
            if r['corpus_id']!=corpus_id:fail('wrong corpus_id')
            if not r['author']:fail('author required')
            if r['kind']!='query' and r['doc_id'] not in docs:fail('unknown doc_id')
            if r['kind'] in ('audit','phrase','mapping','qrel') and not r['evidence'].strip():fail('evidence required')
            if r['kind']=='audit' and r['text']!=docs.get(r['doc_id'],{}).get('text'):fail('audit text differs from corpus')
            if r['kind']=='phrase':
                if not r['text'] or r['text'] not in docs.get(r['doc_id'],{}).get('text',''):fail('phrase not in cited text')
                if r['label'] not in ('valid','incomplete','generic','uncertain'):fail('invalid phrase label')
            if r['kind']=='mapping':
                if r['label'] not in ('synonym','near_synonym','contextual'):fail('invalid relation type')
                if not r['text'] or not r['target'] or r['target'] not in docs.get(r['doc_id'],{}).get('text',''):fail('mapping requires colloquial text and a literal target in source')
            if r['kind']=='query':
                queries[r['id']]=r
                if not r['text'].strip():fail('empty query')
                if r['label'] not in ('development','demo','user_study'):fail('invalid query split')
    for r in rows:
        if r['kind']=='qrel':
            label=r['id'];pair=(r['query_id'],r['doc_id'])
            if r['query_id'] not in queries:errors.append(label+': unknown query_id')
            if pair in pairs:errors.append(label+': duplicate judgment')
            pairs.add(pair)
            if r['label'] not in ('0','1','2'):errors.append(label+': relevance must be 0/1/2')
    if errors:raise ValueError('\n'.join(errors))
    return {'rows_checked':len(rows),'queries':len(queries),'judgments':len(pairs)}
