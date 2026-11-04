"""Question intent is separate from preserved source and TTS delivery."""
import asyncio
import json

import pytest

from backend.src.voice_gateway.knowledge.store import KnowledgeStore
from backend.src.voice_gateway.pipeline import VoicePipeline, VoicePipelineError
from backend.src.voice_gateway.test_pipeline import FakeSTT, FakeTTS
from backend.src.voice_gateway.test_recorder_dialogue import DialogueAgent, question


@pytest.mark.parametrize('valid_audio', [True, False])
def test_follow_up_only_after_validated_question_audio(tmp_path, valid_audio):
    async def run():
        vault = tmp_path / 'vault'; vault.mkdir()
        knowledge = KnowledgeStore(vault, tmp_path/'state')
        audio = tmp_path/'turn'/'input.pcm'; audio.parent.mkdir(); audio.write_bytes(b'\0\0'*200)
        pipeline = VoicePipeline(FakeSTT(), DialogueAgent(question), None,
            FakeTTS(rate=24000 if valid_audio else 16000), knowledge=knowledge)
        job = dict(audio_path=str(audio), turn_id='turn', request_id='request', device_id='mic',
                   created_at='2026-11-04T12:00:00+00:00', audio_bytes=audio.stat().st_size)
        if valid_audio:
            await pipeline.run(job)
            pending = pipeline.text_processor.dialogue.pending('mic')
            assert json.loads((audio.parent/'follow-up.json').read_text()) == dict(
                question_id=pending['question_id'], listen=True)
            # Retrying the durable question keeps the same ID and single journal entry.
            await pipeline.run(job)
            assert pipeline.text_processor.dialogue.pending('mic')['question_id'] == pending['question_id']
        else:
            with pytest.raises(VoicePipelineError, match='tts_failed'):
                await pipeline.run(job)
            assert pipeline.text_processor.dialogue.pending('mic')
            assert not (audio.parent/'follow-up.json').exists()
        assert audio.exists()
        assert not list((knowledge.root/'sources').glob('*.md'))
        assert knowledge.context('mic','','')['recent_sources'][0]['transcript']=='тестовая фраза'
    asyncio.run(run())


def test_explicit_session_reset_retires_pending_without_deleting_evidence(tmp_path):
    from backend.src.voice_gateway.dialogue import DialogueStore
    from backend.src.voice_gateway.models.hermes_response import Clarification
    store = DialogueStore(tmp_path/'dialogue.sqlite')
    pending = store.apply('mic','source',Clarification(question='Что?',source_ids=['source']),None,None)
    store.reset('mic')
    assert store.pending('mic') is None
    assert store.for_source('source')['question_id'] == pending['question_id']
