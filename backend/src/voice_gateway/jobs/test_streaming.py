"""Actual socket tests: ASGI/TestClient buffering cannot prove early delivery."""
import asyncio,hashlib,json,os,socket,tempfile,threading,uuid
import pytest
from pathlib import Path
import httpx,uvicorn
from fastapi import FastAPI
from backend.src.voice_gateway.jobs.store import VoiceJobStore
from backend.src.voice_gateway.jobs.worker import VoiceJobWorker
from backend.src.voice_gateway.jobs.api import install_voice_job_routes
from backend.src.voice_gateway.tts.openai_compatible import OpenAICompatibleTTS
from backend.src.voice_gateway.tts.test_openai_compatible import _config,_metadata_wav

async def check(fail=False,cancel=False,mp3=False):
 with tempfile.TemporaryDirectory() as d:
  root=Path(d);store=VoiceJobStore(root/'jobs.sqlite',root/'archive');release=threading.Event();provider_done=threading.Event()
  body,pcm=_metadata_wav();data_offset=body.index(b'data')+8
  if mp3:
   from backend.src.voice_gateway.tts.test_mp3 import frame
   body=frame()*50;pcm=body;data_offset=4096-200
  class Upstream(httpx.SyncByteStream):
   def __iter__(self):
    yield body[:data_offset+200]
    assert release.wait(10),'client did not receive early PCM'
    if fail:raise httpx.ReadError('deliberate upstream failure')
    yield body[data_offset+200:];provider_done.set()
  tts=OpenAICompatibleTTS(_config(response_format='mp3' if mp3 else 'pcm'),client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,stream=Upstream(),headers={'content-type':'audio/pcm'}))))
  async def process(job,progress):
   progress('synthesizing');folder=Path(job['audio_path']).parent;part=folder/('reply.mp3.part' if mp3 else 'reply.wav.part')
   def ready(size):
    from backend.src.voice_gateway.archive import atomic_write_json
    atomic_write_json(folder/'reply-stream.json',size if isinstance(size,dict) else {'size':size})
   await asyncio.to_thread(tts.synthesize,'test',part,audio_ready=ready)
   out=folder/('reply.mp3' if mp3 else 'reply.wav');os.replace(part,out);return out
  worker=VoiceJobWorker(store,process);await worker.start();app=FastAPI();install_voice_job_routes(app,store,worker,{'test':'secret','other':'secret2'},resolve_mp3_profile=lambda generation:tts)
  sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen();port=sock.getsockname()[1]
  server=uvicorn.Server(uvicorn.Config(app,log_level='critical'));task=asyncio.create_task(server.serve(sockets=[sock]))
  try:
   while not server.started:await asyncio.sleep(.01)
   async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',timeout=12) as client:
    h={'X-Device-Id':'test','Authorization':'Bearer secret','X-Request-Id':str(uuid.uuid4())}
    if mp3:
     h.update({'Accept':'audio/mpeg','X-Audio-Codecs':'mp3,wav','X-Cue-Generation':'a'*64})
    response=await client.post('/api/voice/turns',headers=h,content=b'\0\0'*100);assert response.status_code==202
    url='/api/voice/turns/'+response.json()['turn_id']
    for _ in range(200):
     status=(await client.get(url,headers=h)).json()
     if status.get('audio_stream_ready'):break
     await asyncio.sleep(.01)
    else:raise AssertionError('stream never advertised')
    assert status['status']=='synthesizing'
    assert (await client.get(url+'/audio',headers=h)).status_code==409
    assert (await client.get(url+'/audio?stream=1')).status_code==401
    assert (await client.get(url+'/audio?stream=1',headers={'X-Device-Id':'other','Authorization':'Bearer secret2'})).status_code==404
    received=b'';failed=False
    try:
     async with client.stream('GET',url+'/audio?stream=1',headers=h) as response:
      assert response.status_code==200 and response.headers['x-accel-buffering']=='no'
      async for block in response.aiter_bytes():
       received+=block
       if not release.is_set():
        assert len(received)>44 and not provider_done.is_set()
        assert (received if mp3 else received[44:])==pcm[:len(received) if mp3 else len(received)-44]
        if cancel:
         stopped=await client.post(url+'/cancel',headers=h);assert stopped.json()['status']=='cancelled'
        release.set()
    except httpx.RemoteProtocolError:failed=True
    await worker.queue.join()
    assert failed==(fail or cancel),(failed,fail,cancel)
    status=(await client.get(url,headers=h)).json();assert status['status']==('cancelled' if cancel else 'failed' if fail else 'ready')
    assert status['audio_stream_consumed']
    restarted=VoiceJobStore(root/'jobs.sqlite',root/'archive');restarted.initialize()
    assert restarted.get(status['turn_id'])['audio_stream_claimed']
    assert not restarted.claim_audio_stream('test',status['turn_id'])
    assert (await client.get(url+'/audio?stream=1',headers=h)).status_code==409
    if mp3:
     plain=await client.get(url+'/audio',headers=h)
     assert plain.status_code==409
    if not fail and not cancel:assert (received if mp3 else received[44:])==pcm
    print('Real TCP early PCM before provider completion; auth, legacy, terminal, no replay; '+('upstream failure' if fail else 'success')+' PASS',flush=True)
  finally:
   release.set();server.should_exit=True;await task;await worker.close()
@pytest.mark.parametrize('fail',[False,True])
def test_live_wav_delivery_and_failure_do_not_replay(fail):
 asyncio.run(check(fail))


def test_cancelled_stream_cannot_be_revived_by_late_producer():
 asyncio.run(check(cancel=True))


@pytest.mark.parametrize('fail',[False,True])
def test_live_mp3_delivery_and_failure_do_not_replay(fail):
 asyncio.run(check(fail,mp3=True))
