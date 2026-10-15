import importlib.util
import tempfile
import unittest
import wave
from pathlib import Path
spec = importlib.util.spec_from_file_location('cue', Path(__file__).with_name('prepare-listening-cue.py'))
cue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cue)
class CueTest(unittest.TestCase):
    def wav(self, path, rate=24000, frames=2400):
        with wave.open(str(path), 'wb') as f:
            f.setparams((1,2,rate,0,'NONE','not compressed'))
            f.writeframes(b'\x01\x00'*frames)
    def test_valid_pcm_and_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); self.wav(p/'in.wav')
            m=cue.prepare(p/'in.wav',p/'out','test-model','test-voice')
            self.assertEqual((p/'out/listening.pcm').stat().st_size,4800)
            self.assertEqual(m['sample_rate'],24000)
            self.assertEqual(m['text'],'Слушаю.')
            self.assertEqual(len(m['sha256']),64)
    def test_bad_input_is_rejected(self):
        for rate,frames in ((16000,2400),(24000,0),(24000,120001)):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d);self.wav(p/'in.wav',rate,frames)
                with self.assertRaises(ValueError):cue.prepare(p/'in.wav',p/'out','m','v')
                self.assertFalse((p/'out/listening.pcm').exists())
    def test_truncated_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.wav(p/'in.wav');b=(p/'in.wav').read_bytes();(p/'in.wav').write_bytes(b[:-2])
            with self.assertRaises(ValueError):cue.prepare(p/'in.wav',p/'out','m','v')
if __name__=='__main__':unittest.main()
