from backend.src.voice_gateway.answers import validate_answer
from backend.src.voice_gateway.models.hermes_response import HermesResponse


def context():
    return {'retrieved_pages':[dict(path='Личное/Отпуск.md',title='Отпуск',content='Лодка ещё не выбрана. Бюджет пока неизвестен.',sha256='a'*64,link='obsidian://open?vault=v&file=x')],
            'search':dict(coverage='bounded_local_scan',truncated=False)}


def test_valid_citations_use_backend_identity_and_exact_supplied_quote():
    response=HermesResponse.model_validate(dict(reply='Лодку пока не выбрали.',answer=dict(status='found',citations=[dict(path='Личное/Отпуск.md',title='Придуманное имя',quote='Лодка ещё не выбрана.')]),note=dict(knowledge=dict(operation='query'))))
    result=validate_answer(response,context())
    assert result['status']=='found'
    assert result['citations'][0]['title']=='Отпуск'
    assert result['citations'][0]['sha256']=='a'*64
    assert result['citations'][0]['link'].startswith('obsidian://')
    assert response.reply=='Лодку пока не выбрали.'


def test_invented_citation_or_missing_support_uses_honest_fallback():
    for citation in (dict(path='../outside.md',quote='Лодка ещё не выбрана.'),dict(path='Личное/Отпуск.md',quote='Лодку забронировали.'),None):
        response=HermesResponse.model_validate(dict(reply='Лодку забронировали!',note=dict(knowledge=dict(operation='query')),
            answer=dict(status='found',citations=[citation] if citation else [])))
        result=validate_answer(response,context())
        assert result['status']=='unsupported'
        assert result['citations']==[]
        assert response.reply!='Лодку забронировали!'
    legacy=HermesResponse.model_validate(dict(reply='Уверенный факт',note=dict(knowledge=dict(operation='query'))))
    assert validate_answer(legacy,context())['status']=='unsupported'


def test_conflict_requires_two_real_quotes_and_not_found_keeps_coverage():
    response=HermesResponse.model_validate(dict(reply='Не нашла бюджет в просмотренных заметках.',answer=dict(status='not_found'),note=dict(knowledge=dict(operation='query'))))
    assert validate_answer(response,context())['search']['coverage']=='bounded_local_scan'
    response.answer.status='conflicting'
    assert validate_answer(response,context())['status']=='unsupported'


def test_citation_ref_resolves_exact_original_spelling_and_unknown_ref_rejected():
    ctx=context();ctx['retrieved_pages'][0]['quotes']=[dict(id='q-0123456789abcdef',quote='Лодка ещё не выбрана.')]
    result=HermesResponse.model_validate(dict(reply='Пока не выбрана',note=dict(knowledge=dict(operation='query')),answer=dict(status='found',citations=[dict(ref='q-0123456789abcdef')])))
    answer=validate_answer(result,ctx)
    assert answer['status']=='found'
    assert answer['citations'][0]['quote']=='Лодка ещё не выбрана.'
    assert answer['citations'][0]['path']=='Личное/Отпуск.md'
    result.answer.citations[0].ref='q-invented'
    assert validate_answer(result,ctx)['status']=='unsupported'


def test_duplicate_quote_ref_and_legacy_forms_cannot_fake_conflict():
    ctx=context();ctx['retrieved_pages'][0]['quotes']=[dict(id='q-0123456789abcdef',quote='Лодка ещё не выбрана.')]
    response=HermesResponse.model_validate(dict(reply='Есть противоречие',note=dict(knowledge=dict(operation='query')),
        answer=dict(status='conflicting',citations=[dict(ref='q-0123456789abcdef'),dict(path='Личное/Отпуск.md',quote='Лодка ещё не выбрана.')])) )
    assert validate_answer(response,ctx)['status']=='unsupported'
