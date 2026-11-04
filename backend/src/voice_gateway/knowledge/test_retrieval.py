from pathlib import Path

from .retrieval import VaultRetrieval


def write(root, path, text):
    target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text);return target


def test_manual_alias_russian_forms_and_long_note_passage(tmp_path):
    write(tmp_path,'Личное/Отпуск.md','---\ntitle: Январская поездка\naliases: [Раджа-Ампат, Raja Ampat]\n---\n'+
          'Нерелевантный вводный текст.\n'*600+'\nДайвинг на Раджа-Ампате: дорогие лодки, состояние моря не выяснено.\n')
    result=VaultRetrieval(tmp_path).search('Что известно о дайвинге на Раджа Ампате?')
    assert result['retrieved_pages'][0]['path']=='Личное/Отпуск.md'
    assert 'дорогие лодки' in result['retrieved_pages'][0]['content']
    assert result['search']['coverage'] == 'bounded_local_scan'
    assert 'pages' not in result


def test_comparison_followup_and_topic_switch(tmp_path):
    write(tmp_path,'Раджа.md','# Раджа Ампат\nДайвинг: лодка ещё не выбрана.')
    write(tmp_path,'Юньнань.md','# Юньнань\nПоездка в январе; дайвинг не планируется.')
    write(tmp_path,'Прошивка.md','# Прошивка\nИсправление микрофона.')
    reader=VaultRetrieval(tmp_path)
    initial=reader.search('Сравни Раджа Ампат и Юньнань в январе')
    assert {p['path'] for p in initial['retrieved_pages']} >= {'Раджа.md','Юньнань.md'}
    prior={'question':'Сравни Раджа Ампат и Юньнань в январе','paths':['Раджа.md','Юньнань.md']}
    follow=reader.search('А какой из них лучше для дайвинга?',prior)
    assert {'Раджа.md','Юньнань.md'} <= {p['path'] for p in follow['retrieved_pages']}
    switched=reader.search('Что с прошивкой микрофона?',prior)
    assert switched['retrieved_pages'][0]['path']=='Прошивка.md'
    assert not reader.search('Галактические ксеноморфы')['retrieved_pages']
    (tmp_path/'Раджа.md').unlink()
    assert 'Раджа.md' not in {p['path'] for p in reader.search('Что там с лодкой?',prior)['retrieved_pages']}


def test_safe_traversal_and_bounds(tmp_path):
    outside=tmp_path.parent/'external-note.md';outside.write_text('Секретные поездки')
    (tmp_path/'link.md').symlink_to(outside)
    (tmp_path/'dirlink').symlink_to(tmp_path.parent,target_is_directory=True)
    for path in ('.obsidian/secret.md','.git/secret.md','.trash/secret.md','attachments/secret.md'):
        write(tmp_path,path,'Поездки и дайвинг')
    (tmp_path/'bad.md').write_bytes(b'\xff\xfe')
    write(tmp_path,'good.md','# Поездки\nДайвинг в январе.')
    result=VaultRetrieval(tmp_path).search('поездками')
    assert [p['path'] for p in result['retrieved_pages']]==['good.md']
    for i in range(6):write(tmp_path,f'путешествие-{i}.md','Поездки дайвинг '+str(i))
    bounded=VaultRetrieval(tmp_path,max_files=2,max_results=1,max_context_chars=100).search('поездки')
    assert bounded['search']['truncated']
    assert len(bounded['retrieved_pages'])<=1
    assert sum(len(p['content']) for p in bounded['retrieved_pages'])<=100


def test_topic_links_supply_adjacent_notes_without_granting_write_context(tmp_path):
    write(tmp_path,'Поездки/Январь.md','# Январский отпуск\nВарианты: [[Раджа]] и [[Юннань]].')
    write(tmp_path,'Поездки/Раджа.md','# Раджа Ампат\nЛодка ещё не выбрана.')
    write(tmp_path,'Поездки/Юннань.md','# Юннань\nПлан изучить горы.')
    result=VaultRetrieval(tmp_path).search('Варианты январского отпуска')
    assert {'Поездки/Январь.md','Поездки/Раджа.md','Поездки/Юннань.md'} <= {p['path'] for p in result['retrieved_pages']}
    assert 'pages' not in result
    for page in result['retrieved_pages']:
        assert len(page['quotes'])<=4
        assert all(q['quote'] in page['content'] for q in page['quotes'])
