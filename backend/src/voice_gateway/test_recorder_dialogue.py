import asyncio

import pytest

from backend.src.voice_gateway.agents.base import AgentReply
from backend.src.voice_gateway.knowledge.store import KnowledgeStore
from backend.src.voice_gateway.models.hermes_response import HermesResponse
from backend.src.voice_gateway.text_turns import TextTurnProcessor, TextTurnError
from backend.src.voice_gateway.test_text_turns import make_request


class DialogueAgent:
    def __init__(self, callback):
        self.callback = callback
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return AgentReply(**self.callback(request), thread_id='t', model='m', provider='test')


def question(request):
    return dict(reply='Это отпуск?', note=dict(knowledge=dict(operation='query')),
                clarification=dict(question='Это отпуск?', source_ids=[request.knowledge_context['source_id']]))


def test_typed_clarification_is_not_inferred_from_punctuation():
    parsed = HermesResponse.model_validate(dict(reply='Вопрос?', clarification=dict(
        question='Это отпуск?', source_ids=['source-1'])))
    assert parsed.clarification.question == 'Это отпуск?'
    assert HermesResponse(reply='Вопрос?').clarification is None


def test_pending_survives_restart_and_short_answer_resolves_original(tmp_path):
    async def run():
        vault = tmp_path / 'vault'; vault.mkdir()
        knowledge = KnowledgeStore(vault, tmp_path / 'state')
        agent = DialogueAgent(question)
        processor = TextTurnProcessor(agent, knowledge=knowledge)
        first = await processor.process(make_request(archive_dir=tmp_path / 'one'))
        assert first.clarification['question'] == first.reply == 'Это отпуск?'
        question_id = first.clarification['question_id']
        source = first.receipt['source_id']
        def answer(request):
            pending = request.knowledge_context['pending_clarification']
            assert pending['source_ids'] == [source]
            assert pending['sources'][0]['transcript'] == 'новая идея'
            assert request.knowledge_context['answer_to'] == question_id
            return dict(reply='Поняла', note=dict(create=True, title='Отпуск', content='План отпуска.',
                        knowledge=dict(operation='capture', pages=[], evidence_sources=[source])),
                        dialogue_resolution=dict(question_id=question_id, action='answered'))
        other = TextTurnProcessor(DialogueAgent(answer), knowledge=KnowledgeStore(vault, tmp_path / 'state'))
        result = await other.process(make_request(2, 'да', archive_dir=tmp_path / 'two', answer_to=question_id))
        assert result.receipt['operation'] == 'capture'
        assert other.dialogue.pending('mic') is None
        assert (vault / 'Затея' / 'sources' / f'{source}.md').exists()
    asyncio.run(run())


def test_invalid_source_rejected_and_no_question_persisted(tmp_path):
    async def run():
        vault = tmp_path / 'vault'; vault.mkdir()
        agent = DialogueAgent(lambda r: {**question(r), 'clarification':dict(question='Что?',source_ids=['invented'])})
        processor = TextTurnProcessor(agent, knowledge=KnowledgeStore(vault, tmp_path / 'state'))
        with pytest.raises(TextTurnError, match='agent_invalid_response'):
            await processor.process(make_request(archive_dir=tmp_path / 'one'))
        assert processor.dialogue.pending('mic') is None
    asyncio.run(run())


@pytest.mark.parametrize('action', ['declined', 'superseded'])
def test_model_can_decline_or_switch_topic_without_command_parser(tmp_path, action):
    async def run():
        vault = tmp_path / 'vault'; vault.mkdir()
        knowledge = KnowledgeStore(vault, tmp_path / 'state')
        processor = TextTurnProcessor(DialogueAgent(question), knowledge=knowledge)
        first = await processor.process(make_request(archive_dir=tmp_path / 'one'))
        qid = first.clarification['question_id']
        processor.agent = DialogueAgent(lambda r: dict(reply='Хорошо', note=dict(knowledge=dict(operation='query')),
            dialogue_resolution=dict(question_id=qid, action=action)))
        await processor.process(make_request(2, 'другая мысль', archive_dir=tmp_path / 'two'))
        assert processor.dialogue.pending('mic') is None
    asyncio.run(run())


def test_expiry_context_isolation_idempotency_and_chain_limit(tmp_path):
    from backend.src.voice_gateway.dialogue import DialogueStore
    from backend.src.voice_gateway.models.hermes_response import Clarification, DialogueResolution
    now = [100.0]
    store = DialogueStore(tmp_path / 'dialogue.sqlite', ttl_seconds=900, clock=lambda: now[0])
    cue = Clarification(question='Это отпуск?', source_ids=['source'])
    pending = store.apply('mic', 'source', cue, None, None)
    assert store.pending('other') is None
    assert store.apply('mic', 'source', cue, None, None) == pending
    for depth in range(2, 5):
        pending = store.apply('mic', f'source-{depth}', cue,
            DialogueResolution(question_id=pending['question_id'], action='answered'), pending)
        assert pending['depth'] == depth
        assert pending['listen'] is (depth <= 3)
    now[0] += 901
    assert store.pending('mic') is None
    assert store.for_source('source') is not None


def test_job_metadata_is_durable_and_duplicate_association_is_checked(tmp_path):
    from backend.src.voice_gateway.jobs.store import VoiceJobStore, JobConflict
    store = VoiceJobStore(tmp_path/'jobs.sqlite', tmp_path/'archive'); store.initialize()
    qid = '12345678-1234-1234-1234-123456789abc'
    _, job = store.claim_upload('mic', 'request', answer_to=qid)
    assert job['answer_to'] == qid
    with pytest.raises(JobConflict, match='idempotency_conflict'):
        store.claim_upload('mic', 'request', answer_to=None)
    store.mark_upload_failed(job['turn_id'], 'audio_invalid')
    _, job = store.claim_upload('mic', 'request', answer_to=qid)
    with store._connect() as db:
        db.execute("UPDATE voice_jobs SET status='running' WHERE turn_id=?", (job['turn_id'],))
    store.finish(job['turn_id'], 'ready', result='reply.wav', follow_up=dict(question_id=qid,listen=True))
    assert store.get(job['turn_id'])['follow_up'] == dict(question_id=qid,listen=True)


def test_omitted_resolution_cannot_reset_listen_chain(tmp_path):
    from backend.src.voice_gateway.dialogue import DialogueStore
    from backend.src.voice_gateway.models.hermes_response import Clarification
    store = DialogueStore(tmp_path / 'dialogue.sqlite')
    pending = None
    for depth in range(1, 6):
        pending = store.apply('mic', f'source-{depth}', Clarification(question='Что?', source_ids=['source']), None, pending)
        assert pending['depth'] == depth
        assert pending['listen'] is (depth <= 3)


def test_old_pending_source_is_publishable_after_recent_window(tmp_path):
    async def run():
        vault = tmp_path / 'vault'; vault.mkdir()
        k = KnowledgeStore(vault, tmp_path / 'state')
        p = TextTurnProcessor(DialogueAgent(question), knowledge=k)
        first = await p.process(make_request(archive_dir=tmp_path / 'first'))
        source = first.receipt['source_id']
        for i in range(8):
            k.capture(dict(device_id='mic',request_id=f'interlude-{i}',turn_id=f'interlude-{i}',
                           created_at='2026-11-04'), 'Другая исходная реплика')
        def answer(r):
            assert source not in [s['source_id'] for s in r.knowledge_context['recent_sources']]
            return dict(reply='Готово',note=dict(create=True,title='Отпуск',content='Поездка в январе.',
                knowledge=dict(operation='capture',pages=[],evidence_sources=[source,r.knowledge_context['source_id']])),
                dialogue_resolution=dict(question_id=first.clarification['question_id'],action='answered'))
        p.agent=DialogueAgent(answer)
        result=await p.process(make_request(2,'Да',archive_dir=tmp_path/'answer'))
        assert result.receipt.get('status') != 'needs_review'
        assert p.dialogue.pending('mic') is None
        assert f'[[Затея/sources/{source}|' in (k.root/'ideas/Отпуск.md').read_text()
    asyncio.run(run())


def test_question_retry_reuses_original_decision_without_model(tmp_path):
    async def run():
        vault=tmp_path/'vault';vault.mkdir()
        k=KnowledgeStore(vault,tmp_path/'state')
        agent=DialogueAgent(question)
        p=TextTurnProcessor(agent,knowledge=k)
        request=make_request(archive_dir=tmp_path/'first')
        first=await p.process(request)
        def unexpected(_):
            raise AssertionError('Replay must not invoke model again')
        p=TextTurnProcessor(DialogueAgent(unexpected),knowledge=KnowledgeStore(vault,tmp_path/'state'))
        second=await p.process(request)
        assert second.reply==first.reply
        assert second.clarification==first.clarification
        assert not (k.root/'ideas').exists()
    asyncio.run(run())
