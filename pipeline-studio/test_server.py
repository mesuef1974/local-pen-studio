import base64,io,json,unittest
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image,ImageDraw
import server

def source():
    image=Image.new('RGB',(100,120),'white');ImageDraw.Draw(image).rectangle((20,20,80,100),outline='black',width=3)
    b=io.BytesIO();image.save(b,format='PNG');return 'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()

class PipelineServerTests(unittest.TestCase):
    def setUp(self):server.MODEL_CACHE.clear()
    def test_opaque_preparation_allowed_only_for_pipeline(self):
        data={'image':source(),'settings':{'background':'keep','style':'gray','contrast':100,'denoise':0}}
        result=server.process('/api/prepare',data);self.assertFalse(result['meta']['transparent']);self.assertEqual(result['inputHash'],server.digest(data['image']))
        from preparation import prepare
        with self.assertRaises(ValueError):prepare(data)
    def test_model_cache_and_payload_match_exact_input(self):
        image=source();payload={'image':image,'resolution':768}
        result=SimpleNamespace(returncode=0,stdout=json.dumps({'image':image,'width':100,'height':120,'device':'test','seconds':1}))
        with patch.object(server.subprocess,'run',return_value=result) as call:
            first=server.infer(payload);second=server.infer(payload)
            self.assertEqual(call.call_count,1);self.assertEqual(json.loads(call.call_args.kwargs['input'])['image'],image)
        self.assertFalse(first['cached']);self.assertTrue(second['cached']);self.assertEqual(first['inputHash'],server.digest(image))
    def test_real_preparation_post_and_paths_share_approved_image(self):
        image=source();prep=server.process('/api/prepare',{'image':image,'settings':{'background':'keep','style':'gray','denoise':0,'contrast':100}})
        post=server.process('/api/post',{'image':prep['image'],'settings':{'strength':100}})
        paths=server.process('/api/paths',{'image':post['image'],'lineMode':'centerline','lineDenoise':0,'minLength':2,'tolerance':0})
        self.assertGreater(len(paths['paths']),0);self.assertEqual(paths['inputHash'],server.digest(post['image']))
    def test_invalid_resolution_rejected_before_subprocess(self):
        for value in [True,999,'768']:
            with patch.object(server.subprocess,'run') as call,self.assertRaises(ValueError):server.infer({'image':source(),'resolution':value})
            call.assert_not_called()
    def test_asset_allowlist_has_no_arbitrary_source_access(self):
        for route in ['/server.py','/../trace-studio/processing.py','/.env','/models/sk_model.pth']:
            self.assertNotIn(route,server.ASSETS)
    def handler(self,path):
        handler=object.__new__(server.Handler);handler.server=SimpleNamespace(server_port=8769);handler.path=path
        headers=Message();headers['Host']='127.0.0.1:8769';headers['Origin']='http://127.0.0.1:8769';headers['Content-Type']='application/json';headers['Content-Length']='2'
        handler.headers=headers;handler.rfile=io.BytesIO(b'{}');return handler
    def test_compute_gate_released_before_response_write(self):
        handler=self.handler('/api/model');responses=[]
        handler.reply=lambda code,data:responses.append((code,server.GATE.locked()))
        with patch.object(server,'process',return_value={'ok':True}):handler.do_POST()
        self.assertEqual(responses,[(200,False)])
    def test_import_is_not_blocked_by_another_computation(self):
        handler=self.handler('/api/import');responses=[];handler.reply=lambda code,data:responses.append(code)
        server.GATE.acquire()
        try:
            with patch.object(server,'process',return_value={'ok':True}) as call:handler.do_POST();call.assert_called_once()
            self.assertEqual(responses,[200]);self.assertTrue(server.GATE.locked())
        finally:server.GATE.release()

if __name__=='__main__':unittest.main()
