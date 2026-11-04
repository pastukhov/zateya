import uuid
import pytest
from backend.src.voice_gateway.jobs.store import VoiceJobStore, JobConflict


def test_codec_and_generation_survive_restart_and_retries(tmp_path):
    store=VoiceJobStore(tmp_path/'jobs.db',tmp_path/'archive');store.initialize()
    request=str(uuid.uuid4());generation='a'*64
    _,job=store.claim_upload('d',request,audio_codec='mp3',cue_generation=generation)
    assert job['audio_codec']=='mp3' and job['cue_generation']==generation
    restarted=VoiceJobStore(store.database,store.archive_root);restarted.initialize()
    assert restarted.get(job['turn_id'])['cue_generation']==generation
    with pytest.raises(JobConflict,match='idempotency_conflict'):
        restarted.claim_upload('d',request,audio_codec='wav')


def test_upload_requires_supported_complete_generation_before_claim(tmp_path):
    import asyncio,httpx
    from fastapi import FastAPI
    from backend.src.voice_gateway.jobs.api import install_voice_job_routes
    store=VoiceJobStore(tmp_path/'jobs.db',tmp_path/'archive');store.initialize()
    class Worker:
        async def enqueue(self,turn):pass
    def resolver(generation):
        if generation!='a'*64:raise ValueError('unknown')
        return object()
    app=FastAPI();install_voice_job_routes(app,store,Worker(),{'d':'token'},resolve_mp3_profile=resolver)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            h={'X-Device-Id':'d','Authorization':'Bearer token','X-Request-Id':str(uuid.uuid4()),'X-Audio-Codecs':'mp3,wav'}
            response=await client.post('/api/voice/turns',headers=h,content=b'\0\0')
            assert response.status_code==409
            assert store.get_by_request('d',h['X-Request-Id']) is None
            h['X-Cue-Generation']='a'*64
            response=await client.post('/api/voice/turns',headers=h,content=b'\0\0')
            assert response.status_code==202
            job=store.get_by_request('d',h['X-Request-Id'])
            assert job['audio_codec']=='mp3' and job['cue_generation']=='a'*64
    asyncio.run(run())


def test_worker_validates_mp3_as_negotiated_codec(tmp_path):
    from backend.src.voice_gateway.jobs.worker import VoiceJobWorker
    from backend.src.voice_gateway.tts.test_mp3 import frame
    path=tmp_path/'reply.mp3';path.write_bytes(frame()*2)
    assert VoiceJobWorker._valid_reply(path, 'mp3')
    assert not VoiceJobWorker._valid_reply(path, 'wav')
    path.write_bytes(frame()[:-1])
    assert not VoiceJobWorker._valid_reply(path, 'mp3')


def test_status_keeps_stream_available_when_part_renamed_during_stat(tmp_path,monkeypatch):
    import asyncio,httpx,json,os
    from pathlib import Path
    from fastapi import FastAPI
    from backend.src.voice_gateway.jobs.api import install_voice_job_routes
    from backend.src.voice_gateway.tts.test_mp3 import frame
    folder=tmp_path/'turn';folder.mkdir();part=folder/'reply.mp3.part';final=folder/'reply.mp3'
    data=frame()*2;part.write_bytes(data)
    (folder/'reply-stream.json').write_text(json.dumps({'codec':'mp3','available_bytes':len(data)}))
    job={'turn_id':str(uuid.uuid4()),'request_id':str(uuid.uuid4()),'status':'synthesizing','audio_path':str(folder/'input.pcm')}
    class Store:
        archive_root=tmp_path
        def get_owned(self,device,turn):return job
    app=FastAPI();install_voice_job_routes(app,Store(),object(),{'d':'token'})
    original=Path.stat;original_exists=Path.exists;renamed=[]
    def race(path,*args,**kwargs):
        if path==part and not renamed:
            # exists() succeeded, then the producer atomically finalized it.
            renamed.append(True);os.replace(part,final)
            raise FileNotFoundError(2, 'renamed', str(part))
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'exists',lambda path: True if path==part else original_exists(path))
    monkeypatch.setattr(Path,'stat',race)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.get('/api/voice/turns/'+job['turn_id'],headers={'X-Device-Id':'d','Authorization':'Bearer token'})
            assert response.status_code==200 and response.json().get('audio_stream_ready') is True
    asyncio.run(run());assert renamed
