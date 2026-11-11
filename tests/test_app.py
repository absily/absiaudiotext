import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import app as svc

URL = 'https://www.absi.cc/2026/11/bawndi.html'

def test_article_key():
    assert svc.article_key(URL) == 'articles/2026/11/bawndi.mp3'

@pytest.mark.parametrize('url', ['https://evil.example/2026/11/post.html', 'http://www.absi.cc/2026/11/post.html', 'https://www.absi.cc/anything', 'https://www.absi.cc.evil.test/2026/11/post.html'])
def test_reject_other_domain(url):
    with pytest.raises(ValueError):
        svc.article_key(url)

def test_clean_html():
    assert svc.clean_text('<div>مرحبا <script>bad()</script> بالعالم</div>') == 'مرحبا بالعالم'

def test_no_silent_truncation():
    text = 'ص' * (svc.MAX_CHARS + 1)
    assert len(svc.clean_text(text)) > svc.MAX_CHARS

def test_chunks():
    assert ' '.join(svc.chunks('هذا نص عربي. هذا نص ثان.')) == 'هذا نص عربي. هذا نص ثان.'

def test_authentication(monkeypatch):
    monkeypatch.setenv('WORKER_SHARED_SECRET','very-secret')
    response=TestClient(svc.app).post('/generate', json={'url':URL,'html':'<p>'+'محتوى '*15+'</p>'})
    assert response.status_code == 401

def test_too_long_never_synthesized(monkeypatch):
    monkeypatch.setenv('WORKER_SHARED_SECRET','very-secret')
    response=TestClient(svc.app).post('/generate', headers={'Authorization':'Bearer very-secret'}, json={'url':URL,'html':'م'* (svc.MAX_CHARS+1)})
    assert response.status_code == 422
    assert 'No partial recording' in response.json()['detail']

def test_generate_upload_and_cache(monkeypatch):
    monkeypatch.setenv('WORKER_SHARED_SECRET','very-secret')
    monkeypatch.setenv('R2_BUCKET','absi-audio')
    from botocore.exceptions import ClientError
    s3=MagicMock()
    s3.head_object.side_effect=[ClientError({'Error': {'Code':'404'}, 'ResponseMetadata': {'HTTPStatusCode':404}},'HeadObject'), {}]
    monkeypatch.setattr(svc, 'r2_client', lambda:s3)
    monkeypatch.setattr(svc, 'make_mp3', lambda text:b'ID3' + b'fake mp3 content')
    payload={'url':URL,'html':'<p>'+('هذا مقال تجريبي جيد. '*5)+'</p>'}
    headers={'Authorization':'Bearer very-secret'}
    client=TestClient(svc.app)
    first=client.post('/generate',json=payload,headers=headers)
    assert first.status_code==200
    assert first.json()['status']=='created'
    assert s3.put_object.call_count==1
    second=client.post('/generate',json=payload,headers=headers)
    assert second.status_code==200
    assert second.json()['status']=='already_exists'
    assert s3.put_object.call_count==1

def test_invalid_mp3_never_uploaded(monkeypatch):
    monkeypatch.setenv('WORKER_SHARED_SECRET','very-secret')
    monkeypatch.setenv('R2_BUCKET','absi-audio')
    from botocore.exceptions import ClientError
    s3=MagicMock()
    s3.head_object.side_effect=ClientError({'Error':{'Code':'404'},'ResponseMetadata': {'HTTPStatusCode':404}},'HeadObject')
    monkeypatch.setattr(svc, 'r2_client', lambda:s3)
    monkeypatch.setattr(svc, 'make_mp3', lambda text:b'invalid')
    payload={'url':URL,'html':'<p>'+('هذا مقال تجريبي جيد. '*5)+'</p>'}
    response=TestClient(svc.app).post('/generate',headers={'Authorization':'Bearer very-secret'},json=payload)
    assert response.status_code==503
    s3.put_object.assert_not_called()
