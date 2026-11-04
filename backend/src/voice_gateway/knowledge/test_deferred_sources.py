import pytest

from .store import KnowledgeStore, KnowledgeConflict, metadata
from backend.src.voice_gateway.models.hermes_response import HermesNote


def job(number=1):
    return dict(device_id='mic',request_id=f'r{number}',turn_id=f't{number}',created_at='2026-11-04',channel='recorder',client_id='mic')


def hashes(vault):
    return {str(p.relative_to(vault)):p.read_bytes() for p in vault.rglob('*.md')}


def test_first_query_never_creates_markdown_and_evidence_survives_restart(tmp_path):
    vault=tmp_path/'vault';vault.mkdir();(vault/'Personal.md').write_text('Моя заметка')
    before=hashes(vault);store=KnowledgeStore(vault,tmp_path/'state')
    sid=store.capture(job(),'Вопрос про отпуск?',defer=True)
    context=store.context('mic',sid,'Вопрос про отпуск?')
    receipt=store.publish(sid,'mic',HermesNote(knowledge={'operation':'query'}),context,'Не знаю')
    assert receipt['operation']=='query'
    assert hashes(vault)==before
    reloaded=KnowledgeStore(vault,tmp_path/'state')
    assert reloaded.context('mic',sid,'')['recent_sources'][0]['transcript']=='Вопрос про отпуск?'
    assert reloaded.receipt(sid)['operation']=='query'
    with pytest.raises(KnowledgeConflict):reloaded.capture(job(),'Другой вопрос',defer=True)


def test_later_note_materializes_original_clarification_evidence_atomically(tmp_path):
    vault=tmp_path/'vault';vault.mkdir();store=KnowledgeStore(vault,tmp_path/'state')
    first=store.capture(job(),'Неясная мысль об отпуске',defer=True)
    second=store.capture(job(2),'Да, поездка в январе',defer=True)
    context=store.context('mic',second,'да')
    note=HermesNote(create=True,title='Отпуск',content='Поездка в январе.',knowledge=dict(operation='capture',evidence_sources=[first,second]))
    receipt=store.publish(second,'mic',note,context,'готово')
    assert receipt['operation']=='capture'
    original=(store.root/f'sources/{first}.md').read_bytes()
    assert metadata(original)['request_id']=='r1'
    assert metadata(original)['audio_turn_id']=='t1'
    assert b'2026-11-04' in original
    assert 'Неясная мысль' in original.decode()
    assert first in (store.root/'ideas/Отпуск.md').read_text()
