"""Local teaching server, standard library only. Not a public production server."""
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse
from src.services import LawExploreService, ServiceError

EVENT_LOCK = threading.Lock()

def create_server(host='127.0.0.1', port=8765, service=None):
    service = service or LawExploreService()
    assets = {'/': ('index.html','text/html'), '/app.js': ('app.js','text/javascript'), '/style.css': ('style.css','text/css')}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Do not put user queries into HTTP access logs.
            pass

        def send(self, status, payload, content_type='application/json'):
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if content_type == 'application/json' else payload
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            try:
                if url.path in assets:
                    filename, mime = assets[url.path]
                    return self.send(200, (service.root/'frontend'/filename).read_bytes(), mime)
                if url.path.startswith('/docs/'):
                    docs_root = (service.root/'docs').resolve()
                    target = (service.root/unquote(url.path).lstrip('/')).resolve()
                    if docs_root not in target.parents or target.suffix not in ('.md', '.pdf') or not target.is_file():
                        raise ServiceError(404, 'not_found', '找不到指南。')
                    return self.send(200, target.read_bytes(), 'application/pdf' if target.suffix == '.pdf' else 'text/plain')
                if url.path == '/health':
                    return self.send(200, {'status':'ok', 'corpus_id':service.corpus_id})
                if url.path == '/meta':
                    return self.send(200, service.metadata())
                if url.path == '/team':
                    return self.send(200, json.loads((service.root/'config/team.json').read_text(encoding='utf-8')))
                params = parse_qs(url.query, keep_blank_values=True)
                get = lambda k, default='': params.get(k, [default])[0]
                if url.path not in ('/search','/suggest') and not url.path.startswith(('/phrases/','/documents/')):
                    raise ServiceError(404, 'not_found', '找不到這個路徑。')
                service.check_corpus(get('corpus_id'))
                if url.path == '/search':
                    try:
                        top_k = int(get('top_k','5'))
                    except ValueError:
                        raise ServiceError(400, 'invalid_top_k', 'top_k 必須是整數。')
                    return self.send(200, service.search(get('query'), top_k, get('domain') or None))
                if url.path == '/suggest':
                    response = service.search(get('query'))
                    return self.send(200, {k:response[k] for k in ('query','corpus_id','index_id','suggestions')})
                if url.path.startswith('/phrases/'):
                    term = unquote(url.path[len('/phrases/'):])
                    return self.send(200, service.phrase(term, include_evidence=get('evidence') == '1'))
                return self.send(200, service.document(unquote(url.path[len('/documents/'):])) )
            except ServiceError as e:
                self.send(e.status, {'error': {'code':e.code, 'message':e.message}})
            except Exception:
                self.send(500, {'error': {'code':'internal_error', 'message':'伺服器處理失敗，請檢查資料與模組。'}})

        def do_POST(self):
            try:
                if self.path != '/events':
                    raise ServiceError(404, 'not_found', '未知路徑')
                # Optional study logging; disabled until E defines consent/tasks.
                if not service.config['logging_enabled']:
                    return self.send(200, {'stored':False,'reason':'logging_disabled'})
                origin = self.headers.get('Origin')
                if origin and origin != 'http://' + self.headers.get('Host',''):
                    raise ServiceError(403,'bad_origin','不同來源的請求已拒絕')
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 4096:
                    raise ServiceError(400,'invalid_event','事件大小不正確')
                event = json.loads(self.rfile.read(size))
                allowed = {'event','session_id','task_id','variant','corpus_id','index_id','query_length','phrase','doc_id'}
                if not isinstance(event,dict) or set(event)-allowed:
                    raise ServiceError(400,'invalid_event','不允許的欄位；不得傳入姓名或查詢全文')
                required = {'event','session_id','task_id','variant','corpus_id','index_id'}
                if not required <= event.keys() or any(not isinstance(event[k],str) or not event[k] or len(event[k])>150 for k in required):
                    raise ServiceError(400,'invalid_event','缺少事件識別欄位')
                service.check_corpus(event['corpus_id'])
                if event['index_id'] != service.index_id or event['variant'] not in ('A','B') or event['event'] not in ('search','phrase_click','document_open','task_complete'):
                    raise ServiceError(400,'invalid_event','事件或版本不正確')
                if 'query_length' in event and (type(event['query_length']) is not int or not 0 <= event['query_length'] <= 200):
                    raise ServiceError(400,'invalid_event','查詢長度不正確')
                for key in ('phrase','doc_id'):
                    if key in event and (not isinstance(event[key],str) or len(event[key])>200):
                        raise ServiceError(400,'invalid_event','事件欄位過長')
                event['timestamp'] = datetime.now(timezone.utc).isoformat()
                path = service.root/'results/local/events.jsonl'
                with EVENT_LOCK:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open('a', encoding='utf-8') as f:
                        f.write(json.dumps(event,ensure_ascii=False)+'\n')
                self.send(201, {'stored':True})
            except ServiceError as e:
                self.send(e.status, {'error':{'code':e.code,'message':e.message}})
            except (ValueError, TypeError):
                self.send(400, {'error':{'code':'invalid_event','message':'無效事件'}})

    return ThreadingHTTPServer((host, port), Handler)
