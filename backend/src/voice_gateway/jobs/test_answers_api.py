import asyncio
import uuid

import httpx
from fastapi import FastAPI

from .api import install_voice_job_routes
from .store import VoiceJobStore


def ready(store,device,answer=None):
    _,job=store.claim_upload(device,str(uuid.uuid4()))
    with store._connect() as db:db.execute("UPDATE voice_jobs SET status='running' WHERE turn_id=?",(job['turn_id'],))
    store.finish(job['turn_id'],'ready',result='reply.wav',answer=answer,
                 follow_up=dict(question_id=str(uuid.uuid4()),listen=True))
    return job['turn_id']


def test_answer_and_history_are_owned_and_status_stays_legacy_small(tmp_path):
    async def run():
        store=VoiceJobStore(tmp_path/'jobs.sqlite',tmp_path/'archive');store.initialize()
        answer=dict(status='found',reply='Краткий ответ',citations=[dict(path='Личное/Отпуск.md',
                    title='Отпуск',quote='ц'*600,sha256='a'*64,link='obsidian://open?vault=v&file=note') for _ in range(8)])
        own=ready(store,'a',answer);other=ready(store,'b',answer);old=ready(store,'a')
        app=FastAPI();install_voice_job_routes(app,store,object(),{'a':'secret-a','b':'secret-b'})
        headers={'X-Device-Id':'a','Authorization':'Bearer secret-a'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.get(f'/api/voice/turns/{own}/answer')).status_code==401
            assert (await client.get(f'/api/voice/turns/{other}/answer',headers=headers)).status_code==404
            assert (await client.get(f'/api/voice/turns/{old}/answer',headers=headers)).status_code==404
            data=await client.get(f'/api/voice/turns/{own}/answer',headers=headers)
            assert data.json()==answer
            assert 'no-store' in data.headers['cache-control']
            for path in (f'/api/voice/turns/{own}',f'/api/voice/requests/{store.get(own)["request_id"]}'):
                status=await client.get(path,headers=headers)
                assert len(status.content)<768
                assert status.json()['answer_url']==f'/api/voice/turns/{own}/answer'
                assert 'citations' not in status.json()
            assert 'answer_url' not in (await client.get(f'/api/voice/turns/{old}',headers=headers)).json()
            assert (await client.get('/api/voice/history')).status_code==401
            history=(await client.get('/api/voice/history',headers=headers)).json()['turns']
            assert {j['turn_id'] for j in history}=={own,old}
    asyncio.run(run())


def test_answer_size_bound_and_history_limit(tmp_path):
    store=VoiceJobStore(tmp_path/'jobs.sqlite',tmp_path/'archive');store.initialize()
    for _ in range(23):ready(store,'a')
    assert len(store.history('a',limit=1000))==20
    _,job=store.claim_upload('a',str(uuid.uuid4()))
    import pytest
    with pytest.raises(ValueError,match='too large'):
        store.finish(job['turn_id'],'ready',answer={'reply':'x'*65537})
