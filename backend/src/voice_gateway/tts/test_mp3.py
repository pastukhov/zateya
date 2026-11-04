"""Structural MPEG Layer III validation, including arbitrary HTTP boundaries."""
import pytest
from backend.src.voice_gateway.tts.base import TTSProviderError


def frame(index=8, mono=True):
    # MPEG2 Layer III, 24 kHz, 64 kbps, 192 bytes; no CRC.
    rates = (0,8,16,24,32,40,48,56,64,80,96,112,128,144,160)
    size = 72 * rates[index] * 1000 // 24000
    return bytes((255,243,(index << 4) | 4,192 if mono else 0)) + bytes(size-4)


def parser():
    from backend.src.voice_gateway.tts.mp3 import MP3Parser
    return MP3Parser()


@pytest.mark.parametrize('split',range(193))
def test_every_frame_split_preserves_compressed_bytes(split):
    p=parser();body=frame()+frame(9)
    output=p.feed(body[:split])+p.feed(body[split:]);p.finish()
    assert output==body and p.sample_rate==24000 and p.channels==1
    assert p.frames==2 and p.samples==1152


def test_id3_is_bounded_and_preserved_across_single_bytes():
    p=parser();body=b'ID3\x04\x00\x00\x00\x00\x00\x03abc'+frame()*2
    assert b''.join(p.feed(bytes([b])) for b in body)==body
    p.finish()
    assert p.metadata_bytes==13


@pytest.mark.parametrize('body',[b'',b'garbage',frame()[:-1],frame()+b'junk',frame()+frame(mono=False),b'ID3\x04\x00\x00\x7f\x7f\x7f\x7f'])
def test_corruption_profile_changes_and_oversize_metadata_fail(body):
    p=parser()
    with pytest.raises(TTSProviderError):
        p.feed(body);p.finish()


def test_incomplete_frame_is_never_published():
    p=parser();assert p.feed(frame()[:-1])==b''
    assert p.feed(frame()[-1:])==frame()


def test_mp3_transport_publishes_frames_before_eof_and_preserves_bytes(tmp_path):
    import httpx
    from backend.src.voice_gateway.tts.openai_compatible import OpenAICompatibleTTS
    from backend.src.voice_gateway.tts.config import TTSConfig
    path=tmp_path/'reply.mp3.part';events=[];body=frame()*40
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield body[:4096]
            assert events and path.read_bytes()==body[:21*192]
            yield body[4096:]
    tts=OpenAICompatibleTTS(TTSConfig(base_url='https://test/speech',model='test',response_format='mp3'),
        client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,stream=Stream()))))
    result=tts.synthesize('hello',path,audio_ready=events.append)
    assert path.read_bytes()==body and result.codec=='mp3' and result.media_type=='audio/mpeg'
    assert result.audio_path==path and result.sample_rate==24000
    assert all(e['available_bytes']%192==0 for e in events)


def test_mp3_transport_truncation_removes_part(tmp_path):
    import httpx
    from backend.src.voice_gateway.tts.openai_compatible import OpenAICompatibleTTS
    from backend.src.voice_gateway.tts.config import TTSConfig
    path=tmp_path/'reply.mp3.part'
    tts=OpenAICompatibleTTS(TTSConfig(base_url='https://test/speech',model='test',response_format='mp3'),
        client=httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=frame()+frame()[:-1]))))
    with pytest.raises(TTSProviderError):tts.synthesize('hello',path)
    assert not path.exists()


def test_cancel_while_provider_has_not_sent_headers_returns_without_late_writes(tmp_path):
    import threading,time,httpx
    from backend.src.voice_gateway.tts.openai_compatible import OpenAICompatibleTTS
    from backend.src.voice_gateway.tts.config import TTSConfig
    entered=threading.Event();release=threading.Event();cancel=threading.Event();errors=[]
    def handler(_):
        entered.set();release.wait(3)
        return httpx.Response(200,content=frame()*2)
    tts=OpenAICompatibleTTS(TTSConfig(base_url='https://test/speech',model='test',response_format='mp3'),
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    path=tmp_path/'reply.mp3.part'
    def run():
        try:tts.synthesize('test',path,cancel_event=cancel)
        except TTSProviderError as error:errors.append(error)
    thread=threading.Thread(target=run);thread.start();assert entered.wait(1)
    cancel.set();thread.join(.5)
    try:
        assert not thread.is_alive() and errors and not path.exists()
    finally:
        release.set();thread.join(3)
    time.sleep(.05)
    assert not path.exists()


@pytest.mark.parametrize('send_headers',[False,True])
def test_real_tcp_cancel_interrupts_silent_headers_or_body(tmp_path,send_headers):
    import http.server,threading,httpx
    from backend.src.voice_gateway.tts.openai_compatible import OpenAICompatibleTTS
    from backend.src.voice_gateway.tts.config import TTSConfig
    entered=threading.Event();release=threading.Event();cancel=threading.Event();errors=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            if send_headers:
                self.send_response(200);self.send_header('Content-Length','10000');self.end_headers()
                self.wfile.write(frame()*2);self.wfile.flush()
            entered.set();release.wait(3)
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
    tts=OpenAICompatibleTTS(TTSConfig(base_url=f'http://127.0.0.1:{server.server_port}/speech',model='test',response_format='mp3',timeout=5))
    path=tmp_path/'reply.mp3.part'
    def run():
        try:tts.synthesize('test',path,cancel_event=cancel)
        except TTSProviderError as error:errors.append(error)
    thread=threading.Thread(target=run);thread.start()
    try:
        assert entered.wait(2)
        cancel.set();thread.join(.5)
        assert not thread.is_alive() and errors and not path.exists()
    finally:
        release.set();thread.join(6);tts.close();server.shutdown();server.server_close()
