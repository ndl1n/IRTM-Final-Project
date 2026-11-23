"""Project maintenance: python manage.py --help. Owners normally edit their modules only."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent


import sys
from pathlib import Path
import argparse
import csv
import hashlib
import json
import xml.etree.ElementTree as ET
from src.corpus.parser import article_key, parse_official, parse_rental_rules, write_jsonl
from src.corpus.validation import validate_records

def command_build():
    parser = argparse.ArgumentParser()
    parser.add_argument('--extract-full', action='store_true', help='Create bundled subset from downloaded laws.xml')
    args = parser.parse_args()
    config = json.loads((ROOT/'config/project.json').read_text(encoding='utf-8'))
    scopes = json.loads((ROOT/'config/scope.json').read_text(encoding='utf-8'))
    subset = ROOT/'data/seed/official_sample.xml'
    manifest_path = ROOT/'data/seed/source_manifest.json'
    if args.extract_full:
        full = ROOT/'data/raw/official/laws.xml'
        manifest = json.loads(full.with_suffix('.manifest.json').read_text(encoding='utf-8'))
        source = ET.parse(full).getroot()
        out = ET.Element('LAWS', source.attrib)
        for scope in scopes:
            law = next(l for l in source if l.findtext('法規名稱') == scope['law_name'])
            copy = ET.SubElement(out, '法規')
            for tag in ('法規名稱','法規網址','最新異動日期','生效日期','生效內容'):
                ET.SubElement(copy, tag).text = law.findtext(tag)
            content = ET.SubElement(copy, '法規內容')
            for article in law.findall('./法規內容/條文'):
                if article_key(article.findtext('條號')) in scope['articles']:
                    content.append(article)
        subset.parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(out).write(subset, encoding='utf-8', xml_declaration=True)
        manifest['subset_file'] = 'data/seed/official_sample.xml'
        manifest['subset_sha256'] = hashlib.sha256(subset.read_bytes()).hexdigest()
        manifest['subset_method'] = 'Select config/scope.json articles; preserve article text and effective-date notes.'
        manifest['effective_status'] = 'Source snapshot; individual effective status needs human review.'
        previous_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if 'rental_rules' in previous_manifest:
            manifest['rental_rules'] = previous_manifest['rental_rules']
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if hashlib.sha256(subset.read_bytes()).hexdigest() != manifest['subset_sha256']:
        raise ValueError('Source subset hash mismatch')
    records = parse_official(subset, scopes, config['corpus_id'], manifest['retrieved_at'])
    if 'rental_rules' in manifest:
        source = manifest['rental_rules']
        records.extend(parse_rental_rules(ROOT/source['points_file'], source, config['corpus_id']))
        records.sort(key=lambda record: record['doc_id'])
    validate_records(records, config['corpus_id'])
    output = ROOT/config['corpus_path']
    write_jsonl(output, records)
    print('Built %s verified-source records: %s' % (len(records), output))


import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

URL = 'https://sendlaw.moj.gov.tw/PublicData/GetFile.ashx?AuData=CF&DType=RAW_XML'

def command_download():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/raw/official/laws.xml')
    args = parser.parse_args()
    path = ROOT / args.output
    if path.exists():
        raise SystemExit('Snapshot exists; choose a new --output path.')
    with urllib.request.urlopen(URL, timeout=60) as response:
        payload = response.read()
    import xml.etree.ElementTree as ET
    ET.fromstring(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    metadata = {'landing_url': 'https://data.gov.tw/dataset/18289', 'download_url': URL,
                'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload),
                'license': '政府資料開放授權條款第1版', 'file': str(path.relative_to(ROOT))}
    path.with_suffix('.manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(metadata, ensure_ascii=True))


import argparse
import json
import sys
from pathlib import Path
from src.services import LawExploreService
from src.evaluation.metrics import evaluate

def command_example():
    parser=argparse.ArgumentParser()
    parser.add_argument('role',choices=list('ABCDE'))
    args=parser.parse_args()
    service=LawExploreService()
    if args.role=='A':
        result={'metadata':service.metadata(),'rental_documents':[d for d in service.documents if d['domain']=='租賃'],'work':read_work(ROOT/'data/annotations/A.csv')}
    elif args.role=='B':
        result=service.phrase_index.lookup('出租人')
    elif args.role=='C':
        result=service.search('加班工資')
    elif args.role=='D':
        result=service.phrase('修繕')
    else:
        work=read_work(ROOT/'data/annotations/A.csv')
        result={'purpose':'review_required_not_benchmark','queries':[r for r in work if r['kind']=='query'],'judgments':[r for r in work if r['kind']=='qrel']}
    print(json.dumps(result,ensure_ascii=False,indent=2))


import csv
import json
import sys
from pathlib import Path
from src.services import LawExploreService

def write_csv(path, rows, fields):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader();writer.writerows(rows)

def command_export():
    service=LawExploreService()
    out=ROOT/'results/local';out.mkdir(parents=True,exist_ok=True)
    phrases, docs = [], []
    for phrase in service.phrases:
        result=service.phrase_index.lookup(phrase)
        phrases.append({'corpus_id':service.corpus_id,'phrase':phrase,'frequency':result['frequency'],'df':result['df'],'method':result['backend']})
        for d in result['documents']:
            docs.append({'corpus_id':service.corpus_id,'phrase':phrase,'doc_id':d['doc_id'],'tf':d['tf'],'positions_json':json.dumps(d['positions'])})
    write_csv(out/'phrases.csv',phrases,['corpus_id','phrase','frequency','df','method'])
    write_csv(out/'phrase_documents.csv',docs,['corpus_id','phrase','doc_id','tf','positions_json'])
    queries=[{'query_id':r['id'],'query':r['text']} for r in read_work(ROOT/'data/annotations/A.csv') if r['kind']=='query']
    runs=[dict(query_id=q['query_id'],**service.search(q['query'],10)) for q in queries]
    (out/'baseline_run.json').write_text(json.dumps({'corpus_id':service.corpus_id,'index_id':service.index_id,'parameters':{'k1':1.5,'b':0.75,'tokenizer':'unigram_bigram_v1'},'purpose':'starter_examples_not_evaluation','runs':runs},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Wrote real reference outputs to results/local (not research results).')



from src.corpus.annotations import validate_annotations, read_work
import zipfile

def command_check():
    service=LawExploreService()
    print(validate_annotations(ROOT/'data/annotations',service.documents,service.corpus_id))
    for term in service.phrases:
        result=service.phrase_index.lookup(term)
        assert result['frequency']==sum(d['tf'] for d in result['documents'])
        for d in result['documents']:
            assert all(service.by_id[d['doc_id']]['text'][p['start']:p['end']]==term for p in d['positions'])
    print('PASS: corpus, annotation references and original-text positions.')

def command_package():
    output=ROOT/'dist/LawExplore_Starter.zip';output.parent.mkdir(exist_ok=True)
    files=[ROOT/p for p in ['README.md','run.py','manage.py','Start-LawExplore.cmd','.gitignore']]
    for directory in ['src','tests','frontend','config','docs','data/seed','data/processed/official','data/annotations','handoff/D']:
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(set(files)):z.write(p,'LawExplore/'+p.relative_to(ROOT).as_posix())
    print(str(output)+' | '+str(len(files))+' files')

if __name__=='__main__':
    commands={'build':command_build,'check':command_check,'example':command_example,'export':command_export,'download':command_download,'package':command_package}
    if len(sys.argv)<2 or sys.argv[1] not in commands:
        print('Usage: python manage.py {build|check|example A|export|download|package}')
        raise SystemExit(0 if len(sys.argv)<2 or sys.argv[1] in ('-h','--help') else 2)
    command=sys.argv.pop(1)
    commands[command]()

