import json
import threading
import unittest
import urllib.request
import urllib.error
from urllib.parse import urlencode, quote
from src.api.server import create_server
from src.services import LawExploreService

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service=LawExploreService()
        cls.server=create_server(port=0,service=cls.service)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def request(self,path):
        try:
            with urllib.request.urlopen(self.base+path,timeout=5) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:return e.code,e.read()

    def test_end_to_end_search_document_phrase(self):
        corpus=self.service.corpus_id
        status,body=self.request('/search?'+urlencode({'query':'修繕','corpus_id':corpus}))
        self.assertEqual(status,200);data=json.loads(body);self.assertTrue(data['results'])
        status,body=self.request('/documents/'+data['results'][0]['doc_id']+'?corpus_id='+corpus)
        self.assertEqual(status,200);self.assertTrue(json.loads(body)['text'])
        status,body=self.request('/phrases/'+quote('修繕')+'?corpus_id='+corpus)
        self.assertEqual(status,200);self.assertGreater(json.loads(body)['frequency'],0)

    def test_errors_and_static_isolation(self):
        for path in ('/search?query=x','/documents/missing?corpus_id='+self.service.corpus_id,'/data/raw/official/laws.xml','/docs/../config/project.json','/docs/%2e%2e/config/project.json'):
            self.assertEqual(self.request(path)[0],404,path)
        self.assertEqual(self.request('/search?'+urlencode({'query':'','corpus_id':self.service.corpus_id}))[0],400)
        self.assertEqual(self.request('/search?'+urlencode({'query':'x','top_k':'abc','corpus_id':self.service.corpus_id}))[0],400)

    def test_frontend_and_guides(self):
        for path in ('/','/style.css','/app.js','/team','/meta','/health','/docs/TEAM.md','/docs/TECHNICAL.md'):
            status,body=self.request(path);self.assertEqual(status,200,path);self.assertTrue(body)

    def test_logging_disabled(self):
        req=urllib.request.Request(self.base+'/events',data=b'{}',headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as r:self.assertFalse(json.load(r)['stored'])

if __name__=='__main__':unittest.main()
