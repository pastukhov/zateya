import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.src.voice_gateway.knowledge.store import KnowledgeStore, KnowledgeConflict
from backend.src.voice_gateway.models.hermes_response import HermesNote


def capture(store, number=1, text='Хочу вести идеи'):
    job = dict(device_id='mic', request_id=f'request-{number}', turn_id=f'turn-{number}',
               created_at=f'2026-09-25T10:00:{number:02d}+00:00')
    source = store.capture(job, text)
    return source, store.context('mic', source, text), job


def note(source, operation='capture', target=None, pages=True):
    return HermesNote.model_validate(dict(create=True, title='Идеи', content='Вести идеи, бюджет 1000, не 10000.',
        tags=['идеи'], knowledge=dict(operation=operation, target_id=target, pages=[dict(
            path='wiki/concepts/ideas.md', title='Идеи', content='Идеи сохраняются с контекстом.', sources=[source]
        )] if pages else [])))


@pytest.fixture
def store(tmp_path):
    vault = tmp_path / 'vault'
    vault.mkdir()
    return KnowledgeStore(vault, tmp_path / 'state')


def test_capture_publish_and_idempotent_replay(store):
    source, context, job = capture(store)
    receipt = store.publish(source, 'mic', note(source), context, 'untrusted claim')
    assert receipt['reply'].startswith('Сохранила мысль')
    assert receipt['reply'].endswith('Обновила связанную страницу.')
    assert store.capture(job, 'Хочу вести идеи') == source
    assert store.publish(source, 'mic', note(source), context, '') == receipt
    assert (store.root / 'ideas/Идеи.md').exists()
    assert (store.root / 'log.md').read_text().count(source) == 1
    page = (store.root / 'wiki/concepts/ideas.md').read_text()
    assert f'[[Затея/sources/{source}' in page
    assert store.context('mic', source, 'дополни')['active_idea_id'] == source
    with pytest.raises(KnowledgeConflict):
        store.capture(job, 'different source')


def test_amend_preserves_sources_and_uses_same_idea(store):
    first, context, _ = capture(store)
    store.publish(first, 'mic', note(first), context, '')
    second, context, _ = capture(store, 2, 'Не 1000, а 2000')
    result = store.publish(second, 'mic', note(second, 'amend', first, pages=False), context, '')
    assert result['idea_id'] == first
    assert len(list((store.root / 'ideas').glob('*.md'))) == 1
    body = (store.root / 'ideas/Идеи.md').read_text()
    assert first in body and second in body


def test_same_title_gets_numbered_filename_and_stable_idea_id(store):
    first, context, _ = capture(store)
    store.publish(first, 'mic', note(first), context, '')
    second, context, _ = capture(store, 2, 'Ещё одна идея')
    store.publish(second, 'mic', note(second, pages=False), context, '')
    assert (store.root / 'ideas/Идеи.md').exists()
    second_path = store.root / 'ideas/Идеи (2).md'
    assert second_path.exists()
    assert f'idea_id: {second}' in second_path.read_text()
    third, context, _ = capture(store, 3, 'Дополни вторую идею')
    store.publish(third, 'mic', note(third, 'amend', second, pages=False), context, '')
    assert len(list((store.root / 'ideas').glob('*.md'))) == 2
    assert third in second_path.read_text()


def test_title_is_safe_filename_and_source_id_link_resolves(store):
    source, context, _ = capture(store)
    proposed = note(source)
    proposed.title = '  Полив: дача / насос?  '
    proposed.knowledge.pages[0].content = f'Связь с [[Затея/ideas/{source}]].'
    store.publish(source, 'mic', proposed, context, '')
    assert (store.root / 'ideas/Полив дача насос.md').exists()
    page = (store.root / 'wiki/concepts/ideas.md').read_text()
    assert '[[Затея/ideas/Полив дача насос]]' in page


def test_manual_edit_after_context_is_never_overwritten(store):
    first, context, _ = capture(store)
    store.publish(first, 'mic', note(first), context, '')
    second, context, _ = capture(store, 2)
    page = store.root / 'wiki/concepts/ideas.md'
    page.write_text(page.read_text() + '\nПравка вручную\n')
    before = page.read_bytes()
    with pytest.raises(KnowledgeConflict):
        store.publish(second, 'mic', note(second), context, '')
    assert page.read_bytes() == before
    assert not (store.root / 'ideas/Идеи (2).md').exists()


def test_crash_recovery_replays_journal_without_duplicate_log(store, monkeypatch):
    source, context, _ = capture(store)
    original = store._apply
    def crash(changes):
        original(changes[:1])
        raise OSError('simulated power loss')
    monkeypatch.setattr(store, '_apply', crash)
    with pytest.raises(OSError):
        store.publish(source, 'mic', note(source), context, '')
    restored = KnowledgeStore(store.vault, store.state)
    assert restored.receipt(source)['source_id'] == source
    assert (store.root / 'wiki/concepts/ideas.md').exists()


def test_recovery_stops_when_manual_edit_conflicts(store, monkeypatch):
    source, context, _ = capture(store)
    original = store._apply
    def crash(changes):
        original(changes[:1])
        raise OSError('power loss')
    monkeypatch.setattr(store, '_apply', crash)
    with pytest.raises(OSError):
        store.publish(source, 'mic', note(source), context, '')
    page = store.root / 'ideas/Идеи.md'
    page.write_text('Ручная правка после сбоя')
    restored = KnowledgeStore(store.vault, store.state)
    with pytest.raises(KnowledgeConflict):
        restored.receipt(source)
    assert page.read_text() == 'Ручная правка после сбоя'


def test_rejects_unknown_sources_broken_links_and_traversal(store):
    source, context, _ = capture(store)
    proposed = note(source)
    proposed.knowledge.pages[0].sources = ['0' * 32]
    with pytest.raises(KnowledgeConflict):
        store.publish(source, 'mic', proposed, context, '')
    proposed = note(source)
    proposed.content = '[[Затея/wiki/concepts/missing]]'
    with pytest.raises(KnowledgeConflict):
        store.publish(source, 'mic', proposed, context, '')
    with pytest.raises(ValidationError):
        HermesNote.model_validate(dict(knowledge=dict(operation='capture', pages=[dict(
            path='../escape.md', title='x', content='x', sources=[source])])) )
    assert not (store.root / 'ideas/Идеи.md').exists()


def test_rejects_symlink_and_unseen_existing_page(store, tmp_path):
    source, context, _ = capture(store)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (store.root / 'ideas').symlink_to(outside)
    with pytest.raises(KnowledgeConflict):
        store.publish(source, 'mic', note(source), context, '')
    assert list(outside.iterdir()) == []


def test_query_and_plan_do_not_change_active_idea(store):
    first, context, _ = capture(store)
    store.publish(first, 'mic', note(first), context, '')
    second, context, _ = capture(store, 2)
    query = HermesNote.model_validate(dict(knowledge=dict(operation='query')))
    assert store.publish(second, 'mic', query, context, 'Ответ из базы')['reply'] == 'Ответ из базы'
    third, context, _ = capture(store, 3)
    store.publish(third, 'mic', note(third, 'plan', first, pages=False), context, '')
    assert (store.root / 'builds/Идеи.md').exists()
    assert store.context('mic', third, '')['active_idea_id'] == first


def test_lint_detects_broken_links_without_reading_raw_as_instructions(store):
    from backend.src.voice_gateway.knowledge.__main__ import lint
    source, context, _ = capture(store, text='Текст с [[не ссылка]]')
    store.publish(source, 'mic', note(source), context, '')
    assert lint(store.vault) == []
    with (store.root / 'index.md').open('a') as output:
        output.write('\n[[Затея/wiki/concepts/missing]]\n')
    assert lint(store.vault)[0]['kind'] == 'broken_link'


def test_publication_emits_git_outbox_after_files_with_exact_hashes(store):
    import hashlib
    source, context, _ = capture(store)
    store.publish(source, 'mic', note(source), context, '')
    task = json.loads((store.root / f'.sync/{source}.json').read_text())
    assert f'Затея/sources/{source}.md' in task['files']
    assert 'Затея/schema.md' in task['files']
    for path, expected in task['files'].items():
        assert hashlib.sha256((store.vault / path).read_bytes()).hexdigest() == expected
    assert (store.root / '.sync/writer.lock').exists()


def test_context_excludes_unrelated_pages_and_metadata_matches(store):
    from backend.src.voice_gateway.knowledge.store import markdown
    store._write('wiki/concepts/firmware.md', markdown(
        {'title': 'Прошивка', 'type': 'concept', 'sources': []}, 'Прошивка',
        'Проверка устройства. [[Затея/ideas/Путешествие]]'))
    store._write('wiki/concepts/travel.md', markdown(
        {'title': 'Путешествие', 'type': 'concept'}, 'Путешествие', 'Маршрут Хайнань.'))
    source, context, _ = capture(store, text='Еще вариант путешествия на Хайнань')
    assert [p['path'] for p in context['pages']] == ['wiki/concepts/travel.md']


def test_latin_vault_alias_is_normalized_with_link_validation(store):
    source, context, _ = capture(store)
    proposed = note(source)
    proposed.content = '[[Zateya/wiki/concepts/ideas|Идеи]]'
    store.publish(source, 'mic', proposed, context, '')
    assert '[[Затея/wiki/concepts/ideas|Идеи]]' in (store.root / 'ideas/Идеи.md').read_text()
    second, context, _ = capture(store, 2)
    proposed = note(second)
    proposed.content = '[[Zateya/wiki/concepts/missing]]'
    with pytest.raises(KnowledgeConflict, match='broken wiki link'):
        store.publish(second, 'mic', proposed, context, '')
    assert store.receipt(second) is None


def test_model_selected_topic_membership_restart_and_switch(store):
    source, context, _ = capture(store, text='Отпуск в январе 2027')
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel-january-2027.md', 'title': 'Отпуск 2027'}})
    receipt = store.publish(source, 'mic', declaration, context, '')
    assert receipt['topic_path'] == 'wiki/concepts/travel-january-2027.md'
    assert not (store.root / 'ideas').exists()
    second, context, _ = capture(store, 2, 'Раджа Ампат как вариант')
    proposed = note(second, pages=False)
    proposed.knowledge = proposed.knowledge.model_copy(update={'organization': declaration.knowledge.organization})
    store.publish(second, 'mic', proposed, context, '')
    restarted = KnowledgeStore(store.vault, store.state)
    context = restarted.context('mic', second, 'прошивка')
    assert context['active_topic'] == 'wiki/concepts/travel-january-2027.md'
    assert '[[Затея/ideas/Идеи]]' in (store.root / context['active_topic']).read_text()
    assert restarted.context('other', second, '')['active_topic'] is None
    third, context, _ = capture(store, 3, 'Прошивка диктофона')
    firmware = note(third, pages=False)
    firmware.knowledge = firmware.knowledge.model_copy(update={'organization': declaration.knowledge.organization.model_copy(update={
        'topic_path': 'wiki/concepts/firmware.md', 'title': 'Прошивка'})})
    restarted.publish(third, 'mic', firmware, context, '')
    assert restarted.context('mic', third, '')['active_topic'] == 'wiki/concepts/firmware.md'


def test_recent_sources_survive_rejected_publication_and_are_bounded(store):
    for number in range(1, 12):
        source, context, _ = capture(store, number, 'Сырая речь ' + str(number) + 'x' * 2000)
    context = KnowledgeStore(store.vault, store.state).context('mic', source, '')
    assert len(context['recent_sources']) <= 8
    assert sum(len(item['transcript']) for item in context['recent_sources']) <= 12000
    assert context['recent_sources'][-1]['source_id'] == source
    assert context['recent_sources'][-1]['publication_state'] == 'unpublished'
    assert context['recent_sources_truncated']
    assert store.context('other', source, '')['recent_sources'] == []


def test_unknown_topic_and_manual_topic_edit_are_rejected(store):
    first, context, _ = capture(store)
    store.publish(first, 'mic', note(first), context, '')
    second, context, _ = capture(store, 2)
    proposed = note(second, pages=False)
    proposed.knowledge = proposed.knowledge.model_copy(update={'organization':
        __import__('backend.src.voice_gateway.knowledge.models', fromlist=['Organization']).Organization(
            topic_path='wiki/concepts/ideas.md')})
    with pytest.raises(KnowledgeConflict, match='unknown topic'):
        store.publish(second, 'mic', proposed, context, '')


def test_topic_crash_does_not_advance_state_before_recovery(store, monkeypatch):
    source, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    original = store._apply
    monkeypatch.setattr(store, '_apply', lambda changes: (_ for _ in ()).throw(RuntimeError('crash')))
    with pytest.raises(RuntimeError):
        store.publish(source, 'mic', declaration, context, '')
    monkeypatch.setattr(store, '_apply', original)
    recovered = KnowledgeStore(store.vault, store.state)
    assert recovered.context('mic', source, '')['active_topic'] == 'wiki/concepts/travel.md'
    assert recovered.publish(source, 'mic', declaration, context, '') == recovered.receipt(source)


def test_topic_receipt_uses_saved_title_and_preserves_prose_tags(store):
    first, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    store.publish(first, 'mic', declaration, context, '')
    page = store.root / 'wiki/concepts/travel.md'
    page.write_text(page.read_text().replace('tags: []', 'tags: [личное]') + '\nРучной текст\n')
    second, context, _ = capture(store, 2)
    proposed = note(second, pages=False)
    proposed.knowledge = proposed.knowledge.model_copy(update={'organization': declaration.knowledge.organization.model_copy(update={'title': 'Ошибка'})})
    result = store.publish(second, 'mic', proposed, context, '')
    assert 'Отпуск' in result['reply'] and 'Ошибка' not in result['reply']
    assert 'Ручной текст' in page.read_text() and 'личное' in page.read_text()
    assert second in page.read_text()


def test_malformed_topic_markers_reject_without_writes(store):
    first, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    store.publish(first, 'mic', declaration, context, '')
    page = store.root / 'wiki/concepts/travel.md'
    page.write_text(page.read_text() + '\n<!-- zateya:members:start -->\nРучной текст\n<!-- zateya:members:end -->')
    second, context, _ = capture(store, 2)
    proposed = note(second, pages=False)
    proposed.knowledge = proposed.knowledge.model_copy(update={'organization': declaration.knowledge.organization})
    with pytest.raises(KnowledgeConflict, match='managed section'):
        store.publish(second, 'mic', proposed, context, '')
    assert not (store.root / 'ideas').exists()


def test_amend_clears_previous_category_and_membership(store):
    first, context, _ = capture(store)
    proposed = note(first, pages=False)
    from backend.src.voice_gateway.knowledge.models import Organization
    proposed.knowledge.organization = Organization(topic_path='wiki/concepts/travel.md', title='Отпуск')
    store.publish(first, 'mic', proposed, context, '')
    second, context, _ = capture(store, 2)
    correction = note(second, 'amend', first, pages=False)
    correction.knowledge.organization = Organization(topic_path=None)
    correction.knowledge.evidence_sources = [first, second]
    store.publish(second, 'mic', correction, context, '')
    assert 'category:' not in (store.root / 'ideas/Идеи.md').read_text()
    assert '[[Затея/ideas/Идеи]]' not in (store.root / 'wiki/concepts/travel.md').read_text()


def test_rejected_publication_retains_evidence_after_restart(store):
    first, context, _ = capture(store)
    store.publish(first, 'mic', note(first), context, '')
    second, context, _ = capture(store, 2, 'Это был отпуск, а не выпуск')
    page = store.root / 'wiki/concepts/ideas.md'
    page.write_text(page.read_text() + '\nРучная правка\n')
    with pytest.raises(KnowledgeConflict, match='changed'):
        store.publish(second, 'mic', note(second), context, '')
    store.mark_review(second)
    restarted = KnowledgeStore(store.vault, store.state)
    recent = restarted.context('mic', second, '')['recent_sources']
    assert recent[-1] == {'source_id': second, 'transcript': 'Это был отпуск, а не выпуск',
                          'publication_state': 'needs_review'}
    assert restarted.context('other', second, '')['recent_sources'] == []


def test_topic_rename_requires_evidence_and_context_hash(store):
    first, context, _ = capture(store, text='Выпуск в январе')
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/january.md', 'title': 'Январь — требуется уточнение'}})
    store.publish(first, 'mic', declaration, context, '')
    second, context, _ = capture(store, 2, 'Я говорил отпуск в январе 2027, а не выпуск')
    correction = HermesNote(knowledge={'operation': 'organize', 'evidence_sources': [first, second],
        'organization': {'topic_path': 'wiki/concepts/january.md', 'title': 'Отпуск в январе 2027', 'rename': True}})
    store.publish(second, 'mic', correction, context, '')
    page = (store.root / 'wiki/concepts/january.md').read_text()
    assert '# Отпуск в январе 2027' in page
    assert 'Январь — требуется уточнение' in page
    third, context, _ = capture(store, 3)
    correction.knowledge.evidence_sources = []
    with pytest.raises(KnowledgeConflict, match='rename needs evidence'):
        store.publish(third, 'mic', correction, context, '')


def test_active_topic_and_members_are_bounded_and_prioritized(store):
    from backend.src.voice_gateway.knowledge.store import markdown
    for number in range(45):
        store._write(f'wiki/concepts/topic-{number}.md', markdown(
            {'type': 'topic', 'title': str(number), 'sources': []}, str(number), 'Тема'))
    first, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/zz-active.md', 'title': 'Активная'}})
    store.publish(first, 'mic', declaration, context, '')
    for number in range(55):
        store._write(f'ideas/member-{number}.md', markdown({'category': 'wiki/concepts/zz-active'}, str(number), 'Мысль'))
    context = store.context('mic', first, 'Тема')
    assert context['topics'][0]['path'] == 'wiki/concepts/zz-active.md'
    assert len(context['topics']) == 40 and context['topics_truncated']
    assert len(context['topics'][0]['members']) == 50 and context['topics'][0]['members_truncated']
    assert context['pages'][0]['path'] == 'wiki/concepts/zz-active.md'


def test_topic_manual_edit_after_context_rejects_membership_without_idea(store):
    first, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    store.publish(first, 'mic', declaration, context, '')
    second, context, _ = capture(store, 2)
    topic = store.root / 'wiki/concepts/travel.md'
    topic.write_text(topic.read_text() + '\nРучная правка\n')
    before = topic.read_bytes()
    proposed = note(second, pages=False)
    proposed.knowledge.organization = declaration.knowledge.organization
    with pytest.raises(KnowledgeConflict, match='topic changed'):
        store.publish(second, 'mic', proposed, context, '')
    assert topic.read_bytes() == before and not (store.root / 'ideas').exists()


def test_rename_rejects_current_source_only_evidence(store):
    first, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    store.publish(first, 'mic', declaration, context, '')
    second, context, _ = capture(store, 2)
    correction = HermesNote(knowledge={'operation': 'organize', 'evidence_sources': [second],
        'organization': {'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск 2027', 'rename': True}})
    with pytest.raises(KnowledgeConflict, match='prior evidence'):
        store.publish(second, 'mic', correction, context, '')


def test_two_stale_topic_creations_do_not_duplicate_or_overwrite(store):
    first, first_context, _ = capture(store)
    second, second_context, _ = capture(store, 2)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    first_receipt = store.publish(first, 'mic', declaration, first_context, '')
    with pytest.raises(KnowledgeConflict, match='topic changed'):
        store.publish(second, 'mic', declaration, second_context, '')
    assert store.publish(first, 'mic', declaration, first_context, '') == first_receipt
    assert len(list((store.root / 'wiki/concepts').glob('*.md'))) == 1
    assert store.receipt(second) is None


def test_legacy_category_import_preserves_manual_body_and_tags(store):
    from backend.src.voice_gateway.knowledge.store import markdown
    first, context, _ = capture(store)
    store._write('wiki/concepts/travel-january-2027.md', markdown(
        {'type': 'concepts', 'title': 'Отпуск', 'tags': ['личное'], 'sources': [first],
         'aliases': ['Новогодний отпуск']}, 'Отпуск', 'Ручной текст без изменений.'))
    store._write('ideas/Вариант.md', markdown(
        {'type': 'idea', 'category': 'wiki/concepts/travel-january-2027', 'sources': [first]},
        'Вариант', 'Раджа Ампат'))
    second, context, _ = capture(store, 2)
    assert context['topics'][0]['path'] == 'wiki/concepts/travel-january-2027.md'
    proposed = note(second, pages=False)
    from backend.src.voice_gateway.knowledge.models import Organization
    proposed.knowledge.organization = Organization(topic_path=context['topics'][0]['path'])
    store.publish(second, 'mic', proposed, context, '')
    page = (store.root / context['topics'][0]['path']).read_text()
    assert 'Ручной текст без изменений.' in page and 'Новогодний отпуск' in page and 'личное' in page
    assert '[[Затея/ideas/Вариант]]' in page and '[[Затея/ideas/Идеи]]' in page


def test_amend_evidence_must_reference_target(store):
    from backend.src.voice_gateway.knowledge.models import Organization
    first, context, _ = capture(store)
    store.publish(first, 'mic', note(first, pages=False), context, '')
    unrelated, _, _ = capture(store, 2, 'Другая тема')
    third, context, _ = capture(store, 3, 'Уточнение')
    correction = note(third, 'amend', first, pages=False)
    correction.knowledge.organization = Organization()
    correction.knowledge.evidence_sources = [unrelated, third]
    with pytest.raises(KnowledgeConflict, match='evidence must reference target'):
        store.publish(third, 'mic', correction, context, '')


@pytest.mark.parametrize('managed', [True, False])
def test_pages_cannot_overwrite_topic_or_legacy_category_managed_members(store, managed):
    from backend.src.voice_gateway.knowledge.store import markdown
    first, context, _ = capture(store)
    topic = 'wiki/concepts/travel.md'
    if managed:
        store.publish(first, 'mic', HermesNote(knowledge={'operation': 'organize', 'organization': {
            'topic_path': topic, 'title': 'Отпуск'}}), context, '')
    else:
        store._write(topic, markdown({'type': 'concepts', 'title': 'Отпуск', 'sources': [first]}, 'Отпуск', 'Ручной текст'))
        store._write('ideas/Вариант.md', markdown({'category': topic[:-3], 'sources': [first]}, 'Вариант', 'Маршрут'))
    second, context, _ = capture(store, 2, 'Уточнение отпуска')
    # Even an incomplete catalog cannot authorize overwriting a durable category.
    context['topics'] = []
    before = (store.root / topic).read_bytes()
    proposed = note(second, pages=False)
    from backend.src.voice_gateway.knowledge.models import WikiPage
    proposed.knowledge.pages = [WikiPage(path=topic, title='Отпуск', content='Заменить всё', sources=[second])]
    with pytest.raises(KnowledgeConflict, match='topic content must use organization'):
        store.publish(second, 'mic', proposed, context, '')
    assert (store.root / topic).read_bytes() == before
    assert store.receipt(second) is None


def test_deleted_topic_is_not_recreated_from_stale_context(store):
    first, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    store.publish(first, 'mic', declaration, context, '')
    second, context, _ = capture(store, 2)
    (store.root / 'wiki/concepts/travel.md').unlink()
    proposed = note(second, pages=False)
    proposed.knowledge.organization = declaration.knowledge.organization
    with pytest.raises(KnowledgeConflict, match='topic removed'):
        store.publish(second, 'mic', proposed, context, '')
    assert not (store.root / 'wiki/concepts/travel.md').exists()


def test_unrelated_plain_manual_note_does_not_block_membership(store):
    store._write('ideas/manual.md', b'# Manual note\nUser prose without frontmatter\n')
    source, context, _ = capture(store)
    from backend.src.voice_gateway.knowledge.models import Organization
    proposed = note(source, pages=False)
    proposed.knowledge.organization = Organization(topic_path='wiki/concepts/travel.md', title='Отпуск')
    store.publish(source, 'mic', proposed, context, '')
    assert '[[Затея/ideas/Идеи]]' in (store.root / 'wiki/concepts/travel.md').read_text()


def test_explicit_topic_page_is_additive_and_keeps_managed_members(store):
    from backend.src.voice_gateway.knowledge.models import WikiPage
    first, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    store.publish(first, 'mic', declaration, context, '')
    page = store.root / 'wiki/concepts/travel.md'
    page.write_text(page.read_text() + '\nРучной текст\n')
    second, context, _ = capture(store, 2)
    proposed = note(second, pages=False)
    proposed.knowledge.organization = declaration.knowledge.organization
    proposed.knowledge.pages = [WikiPage(path='wiki/concepts/travel.md', title='Отпуск', content='Новый вариант маршрута.', sources=[second])]
    store.publish(second, 'mic', proposed, context, '')
    text = page.read_text()
    assert 'Ручной текст' in text and 'Новый вариант маршрута.' in text
    assert text.count('<!-- zateya:members:start -->') == 1
    assert '[[Затея/ideas/Идеи]]' in text


def test_nested_members_survive_managed_refresh_and_additions_are_deduplicated(store):
    from backend.src.voice_gateway.knowledge.models import Organization, WikiPage
    from backend.src.voice_gateway.knowledge.store import markdown
    first, context, _ = capture(store)
    organization = Organization(topic_path='wiki/concepts/travel.md', title='Отпуск')
    store.publish(first, 'mic', HermesNote(knowledge={'operation': 'organize', 'organization': organization}), context, '')
    store._write('ideas/archive/old.md', markdown({'category': 'wiki/concepts/travel', 'sources': [first]}, 'Старый вариант', 'Маршрут'))
    for number in (2, 3):
        source, context, _ = capture(store, number)
        proposed = note(source, pages=False)
        proposed.knowledge.organization = organization
        proposed.knowledge.pages = [WikiPage(path=organization.topic_path, title='Отпуск', content='Новое пояснение.', sources=[source])]
        store.publish(source, 'mic', proposed, context, '')
    page = (store.root / organization.topic_path).read_text()
    assert '[[Затея/ideas/archive/old]]' in page
    assert page.count('Новое пояснение.') == 1


def test_receipt_does_not_claim_membership_when_disabled(store):
    from backend.src.voice_gateway.knowledge.models import Organization
    source, context, _ = capture(store)
    proposed = note(source, pages=False)
    proposed.knowledge.organization = Organization(topic_path='wiki/concepts/travel.md', title='Отпуск', membership=False)
    result = store.publish(source, 'mic', proposed, context, '')
    assert 'без включения этой заметки' in result['reply']
    assert 'category:' not in (store.root / 'ideas/Идеи.md').read_text()
    assert '[[Затея/ideas/Идеи]]' not in (store.root / 'wiki/concepts/travel.md').read_text()


def test_prior_idea_id_links_resolve_to_actual_path_with_alias_anchor(store):
    from backend.src.voice_gateway.knowledge.models import Organization, WikiPage
    first, context, _ = capture(store)
    original = note(first, pages=False)
    original.title = 'Исходное название'
    store.publish(first, 'mic', original, context, '')
    second, context, _ = capture(store, 2)
    correction = note(second, 'amend', first, pages=False)
    correction.title = 'Новое название'
    store.publish(second, 'mic', correction, context, '')
    third, context, _ = capture(store, 3)
    proposed = note(third, pages=False)
    proposed.content = f'Альтернатива [[Затея/ideas/{first}#Вариант|прежняя идея]].'
    proposed.knowledge.organization = Organization(topic_path='wiki/concepts/travel.md', title='Отпуск')
    proposed.knowledge.pages = [WikiPage(path='wiki/concepts/travel.md', title='Отпуск',
        content=f'[[Затея/ideas/{first}.md#Вариант|Ранее]]', sources=[third])]
    store.publish(third, 'mic', proposed, context, '')
    assert '[[Затея/ideas/Исходное название#Вариант|прежняя идея]]' in (store.root / 'ideas/Идеи.md').read_text()
    assert '[[Затея/ideas/Исходное название#Вариант|Ранее]]' in (store.root / 'wiki/concepts/travel.md').read_text()


@pytest.mark.parametrize('ambiguous', [True, False])
def test_unknown_or_ambiguous_prior_idea_ids_reject(store, ambiguous):
    from backend.src.voice_gateway.knowledge.store import markdown
    first, context, _ = capture(store)
    store.publish(first, 'mic', note(first, pages=False), context, '')
    if ambiguous:
        store._write('ideas/duplicate.md', markdown({'idea_id': first, 'sources': [first]}, 'Дубликат', 'Идеи'))
    second, context, _ = capture(store, 2, 'Идеи')
    proposed = note(second, pages=False)
    identity = first if ambiguous else 'f' * 32
    proposed.content = f'[[Затея/ideas/{identity}|Ранее]]'
    with pytest.raises(KnowledgeConflict, match='idea link'):
        store.publish(second, 'mic', proposed, context, '')


def test_plain_context_page_does_not_block_topic_rename_evidence(store):
    first, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    store.publish(first, 'mic', declaration, context, '')
    store._write('ideas/manual.md', '# отпуск ручная заметка\n'.encode())
    second, context, _ = capture(store, 2, 'Отпуск в январе')
    assert any(p['path'] == 'ideas/manual.md' for p in context['pages'])
    correction = HermesNote(knowledge={'operation': 'organize', 'evidence_sources': [first, second],
        'organization': {'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск в январе', 'rename': True}})
    store.publish(second, 'mic', correction, context, '')
    assert '# Отпуск в январе' in (store.root / 'wiki/concepts/travel.md').read_text()


def test_large_topic_snapshot_supports_membership_and_rename_without_data_loss(store):
    from backend.src.voice_gateway.knowledge.models import Organization
    first, context, _ = capture(store)
    declaration = HermesNote(knowledge={'operation': 'organize', 'organization': {
        'topic_path': 'wiki/concepts/travel.md', 'title': 'Отпуск'}})
    store.publish(first, 'mic', declaration, context, '')
    page = store.root / 'wiki/concepts/travel.md'
    page.write_text(page.read_text() + '\nБольшой ручной текст.\n' * 2000)
    second, context, _ = capture(store, 2)
    snapshot = next(p for p in context['pages'] if p['path'] == 'wiki/concepts/travel.md')
    assert snapshot['content_truncated'] and len(snapshot['content']) < 12000
    proposed = note(second, pages=False)
    proposed.knowledge.organization = Organization(topic_path='wiki/concepts/travel.md', title='Отпуск 2027', rename=True)
    proposed.knowledge.evidence_sources = [first, second]
    store.publish(second, 'mic', proposed, context, '')
    text = page.read_text()
    assert text.count('Большой ручной текст.') == 2000
    assert '# Отпуск 2027' in text and '[[Затея/ideas/Идеи]]' in text


def test_truncated_snapshot_cannot_replace_ordinary_note(store):
    first, context, _ = capture(store)
    store.publish(first, 'mic', note(first, pages=False), context, '')
    second, context, _ = capture(store, 2)
    before = (store.root / 'ideas/Идеи.md').read_bytes()
    next(p for p in context['pages'] if p['path'] == 'ideas/Идеи.md')['content_truncated'] = True
    with pytest.raises(KnowledgeConflict, match='cannot rewrite truncated page'):
        store.publish(second, 'mic', note(second, 'amend', first, pages=False), context, '')
    assert (store.root / 'ideas/Идеи.md').read_bytes() == before
