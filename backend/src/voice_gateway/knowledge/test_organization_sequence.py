"""Scripted model decisions test persistence; these do not prove model semantics."""
from backend.src.voice_gateway.knowledge.models import Organization
from backend.src.voice_gateway.knowledge.store import KnowledgeStore, metadata
from backend.src.voice_gateway.knowledge.test_store import capture, note
from backend.src.voice_gateway.models.hermes_response import HermesNote


def test_free_form_sequence_preserves_alternatives_restart_and_topic_switch(tmp_path):
    vault = tmp_path / 'vault'
    vault.mkdir()
    store = KnowledgeStore(vault, tmp_path / 'state')
    first, context, _ = capture(store, 1, 'Думаю про выпуск в январе')
    pending = HermesNote(knowledge={'operation': 'query'})
    store.publish(first, 'mic', pending, context, 'Ты имеешь в виду отпуск?')
    travel = Organization(topic_path='wiki/concepts/travel-january-2027.md', title='Отпуск в январе 2027')
    second, context, _ = capture(store, 2, 'Отпуск в январе 2027, Раджа Ампат один вариант')
    proposed = note(second, pages=False)
    proposed.title, proposed.content = 'Раджа Ампат', 'Вариант отпуска: Раджа Ампат.'
    proposed.knowledge.organization = travel
    store.publish(second, 'mic', proposed, context, '')
    store = KnowledgeStore(vault, tmp_path / 'state')
    third, context, _ = capture(store, 3, 'Другой вариант Юньнань и Хайнань')
    proposed = note(third, pages=False)
    proposed.title, proposed.content = 'Юньнань и Хайнань', 'Альтернативный вариант: Юньнань и Хайнань.'
    proposed.knowledge.organization = travel
    store.publish(third, 'mic', proposed, context, '')
    fourth, context, _ = capture(store, 4, 'Теперь прошивка диктофона')
    firmware = note(fourth, pages=False)
    firmware.title, firmware.content = 'Прошивка', 'Проверить прошивку диктофона.'
    firmware.knowledge.organization = Organization(topic_path='wiki/concepts/firmware.md', title='Прошивка')
    store.publish(fourth, 'mic', firmware, context, '')
    firmware_before = (store.root / 'wiki/concepts/firmware.md').read_bytes()
    fifth, context, _ = capture(store, 5, 'Вернусь к отпуску: Раджа Ампат пока под вопросом')
    correction = note(fifth, 'amend', second, pages=False)
    correction.title, correction.content = 'Раджа Ампат', 'Раджа Ампат — вариант, пока под вопросом. Уточнение пользователя.'
    correction.knowledge.organization = travel
    correction.knowledge.evidence_sources = [second, fifth]
    receipt = store.publish(fifth, 'mic', correction, context, '')
    assert store.publish(fifth, 'mic', correction, context, '') == receipt
    assert (store.root / 'wiki/concepts/firmware.md').read_bytes() == firmware_before
    topic = (store.root / travel.topic_path).read_text()
    assert '[[Затея/ideas/Раджа Ампат]]' in topic and '[[Затея/ideas/Юньнань и Хайнань]]' in topic
    assert 'Прошивка' not in topic and 'Сычуань' not in topic
    assert metadata((store.root / 'ideas/Юньнань и Хайнань.md').read_bytes())['category'] == travel.topic_path[:-3]
    assert 'выпуск' in (store.root / f'sources/{first}.md').read_text()
    assert len(store.context('mic', fifth, '')['recent_sources']) == 5
    assert store.context('other', fifth, '')['active_topic'] is None
