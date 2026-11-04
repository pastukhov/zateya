import io
import threading
import wave
import httpx
import pytest
from backend.src.voice_gateway.tts.test_openai_compatible import _metadata_wav,_config,_make_client,WAV_24K,_wav_response
from backend.src.voice_gateway.tts.base import TTSProviderError


def test_first_audio_published_before_provider_eof_with_fragmented_metadata(tmp_path):
    body,pcm=_metadata_wav();events=[];path=tmp_path/'reply.wav.part'
    class Delayed(httpx.SyncByteStream):
        def __iter__(self):
            for byte in body:
                yield bytes([byte])
                if path.exists() and path.stat().st_size>44:
                    assert path.read_bytes()[44:]==pcm[:path.stat().st_size-44]
            assert events and path.read_bytes()[44:]==pcm
            events.append('provider_eof')
    client=_make_client(httpx.MockTransport(lambda _:httpx.Response(200,stream=Delayed(),headers={'content-type':'audio/pcm'})),_config(response_format='pcm'))
    result=client.synthesize('hi',path,audio_ready=lambda size:events.append(size),cancel_event=threading.Event())
    assert events==[44+len(pcm),'provider_eof']
    assert result.sample_rate==24000 and path.read_bytes()[44:]==pcm


@pytest.mark.parametrize('unknown,raw',[(True,False),(False,True)])
def test_unsupported_streaming_uses_complete_file_fallback(tmp_path,unknown,raw):
    body,pcm=_metadata_wav(unknown_riff=unknown,unknown_data=unknown)
    if raw:body=pcm
    events=[];path=tmp_path/'out.wav'
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield body[:100]
            assert not events and not path.exists()
            yield body[100:]
    client=_make_client(httpx.MockTransport(lambda _:httpx.Response(200,stream=Stream(),headers={'content-type':'audio/pcm'})),_config(response_format='pcm'))
    client.synthesize('hi',path,audio_ready=events.append)
    assert not events and path.read_bytes()[44:]==pcm


def test_stream_failure_after_audio_is_not_success(tmp_path):
    body,pcm=_metadata_wav();path=tmp_path/'out.wav';events=[]
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield body[:body.index(b'data')+8+100]
            assert events
            raise httpx.ReadError('interrupted')
    client=_make_client(httpx.MockTransport(lambda _:httpx.Response(200,stream=Broken(),headers={'content-type':'audio/wav'})))
    with pytest.raises(TTSProviderError):client.synthesize('hi',path,audio_ready=events.append)
    assert not path.exists()


@pytest.mark.parametrize('broken_tail',[False,True])
def test_complete_pcm_followed_by_failure_never_publishes_success(tmp_path,broken_tail):
    body,pcm=_metadata_wav();path=tmp_path/'out.wav';events=[]
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield body[:body.index(b'data')+8+len(pcm)]
            assert events and path.read_bytes()[44:]==pcm
            if broken_tail:yield body[-3:]
            else:raise httpx.ReadError('trailing metadata request failed')
    client=_make_client(httpx.MockTransport(lambda _:httpx.Response(200,stream=Broken())))
    with pytest.raises(TTSProviderError):client.synthesize('hi',path,audio_ready=events.append)
    assert not path.exists()


def test_cancel_before_data_and_size_limit_leave_no_output(tmp_path):
    from backend.src.voice_gateway.tts.streaming import MAX_TTS_BYTES
    path=tmp_path/'out.wav';events=[];cancel=threading.Event();cancel.set()
    client=_make_client(httpx.MockTransport(lambda _:_wav_response(WAV_24K)))
    with pytest.raises(TTSProviderError):client.synthesize('hi',path,audio_ready=events.append,cancel_event=cancel)
    assert not events and not path.exists()
    body=bytearray(WAV_24K);body[4:8]=(MAX_TTS_BYTES+1).to_bytes(4,'little')
    client=_make_client(httpx.MockTransport(lambda _:_wav_response(bytes(body))))
    with pytest.raises(TTSProviderError):client.synthesize('hi',path,audio_ready=events.append)
    assert not events and not path.exists()


def test_stream_publication_io_error_is_tts_failure_and_removes_partial(tmp_path):
    body,_=_metadata_wav();path=tmp_path/'out.wav'
    client=_make_client(httpx.MockTransport(lambda _:_wav_response(body)))
    def unavailable_marker(_):raise OSError('cannot publish availability')
    with pytest.raises(TTSProviderError,match='OSError'):
        client.synthesize('hi',path,audio_ready=unavailable_marker)
    assert not path.exists()
