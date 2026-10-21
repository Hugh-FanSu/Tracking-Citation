import unittest
from unittest.mock import patch,Mock
from paper_citation_pipeline.ai_review import Client
class GLM53Tests(unittest.TestCase):
 def test_flash_keeps_thinking_enabled_and_json_output(self):
  with patch('paper_citation_pipeline.ai_review.requests.Session') as session:
   response=Mock(status_code=200);response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'usage':{'prompt_tokens':3,'completion_tokens':5},'model':'glm-5.3-flash'}
   session.return_value.post.return_value=response
   cfg={'model':'glm-5.3-flash','endpoint':'https://open.bigmodel.cn/api/paas/v4','max_tokens':4096,'json_mode':True,'timeout':30}
   client=Client(cfg,key='test');result,_=client.request([{'role':'user','content':'test'}],attempts=1)
   payload=session.return_value.post.call_args.kwargs['json']
   self.assertEqual(payload['thinking'],{'type':'enabled'})
   self.assertEqual(payload['reasoning_effort'],'low');self.assertEqual(result,{'ok':True})
   self.assertEqual(payload['response_format'],{'type':'json_object'})
