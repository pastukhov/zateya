"""Ground model answer references in the exact immutable retrieval snapshot."""
from __future__ import annotations


def resolve_citation(item, context):
    pages=(context or {}).get('retrieved_pages',[])
    if item.ref:
        for page in pages:
            for candidate in page.get('quotes',[]):
                if candidate['id']==item.ref:
                    quote=candidate['quote']
                    return (page,quote) if quote.strip() and quote in page['content'] and '\n…\n' not in quote else None
        return None
    page=next((page for page in pages if page['path']==item.path),None)
    if page is None or not item.quote.strip() or '\n…\n' in item.quote or item.quote not in page['content']:
        return None
    return page,item.quote


def validate_answer(response,context):
    context=context or {}
    proposal=response.note.knowledge
    if not proposal or proposal.operation!='query':
        return None
    acknowledgement=response.dialogue_resolution and response.dialogue_resolution.action in {'declined','superseded'}
    if (response.clarification or acknowledgement) and response.answer is None:
        return None
    answer=response.answer
    citations=[];seen=set();valid=answer is not None
    for item in answer.citations if answer else []:
        resolved=resolve_citation(item,context)
        if resolved is None:
            valid=False;break
        page,quote=resolved
        citation={key:page[key] for key in ('path','title','sha256','link')}
        citation['quote']=quote
        if item.ref:citation['ref']=item.ref
        identity=(page["path"],quote)
        if identity not in seen:
            citations.append(citation);seen.add(identity)
    if answer and answer.status=='found' and not citations:valid=False
    if answer and answer.status=='conflicting' and len(citations)<2:valid=False
    if not valid:
        citations=[]
        response.reply='Не могу подтвердить ответ по найденным заметкам. Уточните вопрос или источник.'
    if valid and answer.status=='not_found':
        response.reply='В просмотренных заметках не нашла подтверждения. Поиск ограничен; можно уточнить вопрос или источник.'
    if valid and answer.status=='ambiguous' and response.clarification is None:
        response.reply='В найденных заметках недостаточно данных для однозначного ответа. Уточните, о чём именно речь.'
    if len(response.reply)>2000:
        shortened=response.reply[:1999]
        stop=max(shortened.rfind('. '),shortened.rfind('? '),shortened.rfind('! '))
        response.reply=shortened[:stop+1] if stop>=100 else shortened.rsplit(' ',1)[0]+'…'
    return dict(status=answer.status if valid else 'unsupported',reply=response.reply,
                citations=citations,search=context.get('search',{'coverage':'unavailable','truncated':True}))


def answer_contract_issue(response, context):
    """Safe repair reason; never includes user evidence or credentials."""
    proposal=response.note.knowledge
    if response.answer is None:
        acknowledgement=response.dialogue_resolution and response.dialogue_resolution.action in {'declined','superseded'}
        if (proposal and proposal.operation=='query' and context is not None and
            'retrieved_pages' in context and not response.clarification and not acknowledgement):
            return 'query_requires_grounded_answer'
        return None
    if proposal is None or proposal.operation!='query' or response.note.create or proposal.pages or proposal.organization:
        return 'answer_requires_nonmutating_query'
    quotes=set()
    for item in response.answer.citations:
        resolved=resolve_citation(item,context)
        if resolved is None:
            return 'citation_requires_supplied_ref_or_exact_path_and_quote'
        page,quote=resolved
        quotes.add((page['path'],quote))
    required={'found':1,'conflicting':2}.get(response.answer.status,0)
    return 'answer_requires_supporting_citations' if len(quotes)<required else None
