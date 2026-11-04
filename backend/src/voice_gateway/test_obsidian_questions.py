import asyncio
import json
from dataclasses import replace

import pytest

from backend.src.voice_gateway.agents.base import AgentReply
from backend.src.voice_gateway.knowledge.store import KnowledgeStore
from backend.src.voice_gateway.text_turns import TextTurnProcessor, TextTurnError
from backend.src.voice_gateway.test_text_turns import make_request


class AnswerAgent:
    def __init__(self,callback=None):self.requests=[];self.callback=callback
    async def complete(self,request):
        self.requests.append(request)
        if self.callback:return self.callback(request)
        page=request.knowledge_context['retrieved_pages'][0]
        return AgentReply('Лодка ещё не выбрана.',dict(knowledge=dict(operation='query')),'t','m','test',
            answer=dict(status='found',citations=[dict(ref=next(q['id'] for q in page['quotes'] if q['quote']=='Лодка ещё не выбрана.'))]))


def markdown_snapshot(vault):
    return {str(p.relative_to(vault)):p.read_bytes() for p in vault.rglob('*.md')}


def test_query_citations_retry_restart_and_followup_leave_markdown_unchanged(tmp_path):
    async def run():
        vault=tmp_path/'vault';vault.mkdir();note=vault/'Раджа.md';note.write_text('# Раджа Ампат\nДайвинг. Лодка ещё не выбрана.')
        before=markdown_snapshot(vault);agent=AnswerAgent();k=KnowledgeStore(vault,tmp_path/'state')
        processor=TextTurnProcessor(agent,knowledge=k);request=make_request(text='Что с дайвингом на Раджа Ампате?',archive_dir=tmp_path/'turn')
        first=await processor.process(request)
        assert first.receipt['operation']=='query'
        assert first.answer['status']=='found'
        assert first.answer['citations'][0]['path']=='Раджа.md'
        assert markdown_snapshot(vault)==before
        original=json.loads((tmp_path/'turn/answer.json').read_text())
        restarted=TextTurnProcessor(AnswerAgent(lambda _:pytest.fail('retry invoked model')),knowledge=KnowledgeStore(vault,tmp_path/'state'))
        second=await restarted.process(request)
        assert second.answer==original
        assert markdown_snapshot(vault)==before
        note.write_text('# Раджа Ампат\nДайвинг. Лодка забронирована. Бюджет уточнён.')
        def follow(r):
            assert r.knowledge_context['previous_query']['paths']==['Раджа.md']
            page=r.knowledge_context['retrieved_pages'][0]
            assert 'Лодка забронирована.' in page['content']
            return AgentReply('Лодка забронирована.',dict(knowledge=dict(operation='query')),'t','m','test',
                answer=dict(status='found',citations=[dict(path='Раджа.md',quote='Лодка забронирована.')]))
        restarted.agent=AnswerAgent(follow)
        after_edit=markdown_snapshot(vault)
        result=await restarted.process(make_request(2,'А что с лодкой?',archive_dir=tmp_path/'follow'))
        assert result.answer['citations'][0]['sha256']!=first.answer['citations'][0]['sha256']
        assert markdown_snapshot(vault)==after_edit
        restarted.dialogue.reset('mic')
        assert restarted.dialogue.query_context('mic') is None
        assert restarted.dialogue.query_context('other') is None
    asyncio.run(run())


@pytest.mark.parametrize('with_knowledge',[False,True])
def test_conflicting_retry_never_overwrites_original_archive_or_source(tmp_path,with_knowledge):
    async def run():
        vault=tmp_path/'vault';vault.mkdir()
        if with_knowledge:(vault/'Раджа.md').write_text('Лодка ещё не выбрана. Дайвинг.')
        agent=AnswerAgent() if with_knowledge else AnswerAgent(lambda r:AgentReply('ответ',None,'t','m','test'))
        k=KnowledgeStore(vault,tmp_path/'state') if with_knowledge else None
        p=TextTurnProcessor(agent,knowledge=k)
        request=make_request(text='Дайвинг',archive_dir=tmp_path/'turn')
        await p.process(request)
        original={name:(request.archive_dir/name).read_bytes() for name in ('transcript.txt','text-input.json')}
        for changed in (replace(request,transcript='Другой текст'),replace(request,created_at='2030-01-01')):
            with pytest.raises(TextTurnError,match='knowledge_conflict|idempotency_conflict'):
                await p.process(changed)
            assert {name:(request.archive_dir/name).read_bytes() for name in original}==original
        assert len(agent.requests)==1
    asyncio.run(run())


def test_answer_cannot_be_attached_to_a_mutation(tmp_path):
    async def run():
        vault=tmp_path/'vault';vault.mkdir()
        def invalid(r):return AgentReply('сохранила',dict(create=True,title='x',content='x',knowledge=dict(operation='capture')),'t','m','test',answer=dict(status='not_found'))
        p=TextTurnProcessor(AnswerAgent(invalid),knowledge=KnowledgeStore(vault,tmp_path/'state'))
        with pytest.raises(TextTurnError,match='agent_invalid_response'):
            await p.process(make_request(archive_dir=tmp_path/'turn'))
        assert not list(vault.rglob('*.md'))
    asyncio.run(run())


def test_final_answer_reply_matches_clarification_and_review_clears_metadata(tmp_path):
    async def run():
        vault=tmp_path/'vault';vault.mkdir()
        def clarification(r):return AgentReply('Нужно уточнение',dict(knowledge=dict(operation='query')),'t','m','test',
            clarification=dict(question='Какой вариант отпуска?',source_ids=[r.knowledge_context['source_id']]),answer=dict(status='ambiguous'))
        p=TextTurnProcessor(AnswerAgent(clarification),knowledge=KnowledgeStore(vault,tmp_path/'state'))
        first=await p.process(make_request(archive_dir=tmp_path/'one'))
        assert first.answer['reply']==first.reply=='Какой вариант отпуска?'
        assert json.loads((tmp_path/'one/answer.json').read_text())['reply']==first.reply
        def malformed(r):return AgentReply('Сохранила',dict(create=True,title='x',content='x',knowledge=dict(operation='query')),'t','m','test',answer=dict(status='not_found'))
        p.agent=AnswerAgent(malformed)
        second=await p.process(make_request(2,archive_dir=tmp_path/'two'))
        assert second.receipt['status']=='needs_review'
        assert second.answer is None
        assert not (tmp_path/'two/answer.json').exists()
        assert not list(vault.rglob('*.md'))
    asyncio.run(run())
