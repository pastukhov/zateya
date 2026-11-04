#!/usr/bin/env python3
"""Opt-in provider replay. Always creates a fresh temporary vault; no Git or TTS."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.src.voice_gateway.agents.base import AgentRequest
from backend.src.voice_gateway.agents.config import LLMConfig
from backend.src.voice_gateway.agents.openai_client import OpenAICompatibleAgentClient
from backend.src.voice_gateway.agents.prompts import system_prompt
from backend.src.voice_gateway.agents.sessions import AgentSessionStore
from backend.src.voice_gateway.knowledge.store import KnowledgeConflict, KnowledgeStore, metadata
from backend.src.voice_gateway.models.hermes_response import HermesNote

SEQUENCE = [
    'Думаю про выпуск в январе, надо прикинуть варианты.',
    'Я имел в виду отпуск в январе 2027 года, а не выпуск. Один вариант — Раджа Ампат.',
    'Есть другой вариант того же отпуска: Юньнань и Хайнань. Пока не решил, какой выбрать.',
    'Теперь о другом: в прошивке диктофона нужно проверить буфер записи.',
    'Вернусь к отпуску в январе. Раджа Ампат пока под вопросом, это не окончательный маршрут.',
]


async def replay() -> int:
    config = LLMConfig.from_env()  # Validate before creating artifacts; never print keys.
    root = Path(tempfile.mkdtemp(prefix='zateya-thought-replay-'))
    vault = root / 'vault'
    vault.mkdir()
    state = root / 'state'
    sessions = AgentSessionStore(root / 'sessions.sqlite3')
    client = OpenAICompatibleAgentClient(config, system_prompt(), sessions=sessions)
    records = []
    try:
        for index, transcript in enumerate(SEQUENCE, 1):
            store = KnowledgeStore(vault, state)  # Deliberate restart each turn.
            request = f'replay-{index}'
            job = dict(device_id='isolated-replay', request_id=request, turn_id=request,
                       created_at=f'2026-11-04T12:00:{index:02d}+00:00')
            source = store.capture(job, transcript)
            context = store.context(job['device_id'], source, transcript)
            reply = await client.complete(AgentRequest(request, job['device_id'], transcript, context))
            note = HermesNote.model_validate(reply.note or {})
            try:
                receipt = store.publish(source, job['device_id'], note, context, reply.reply)
            except KnowledgeConflict as exc:
                store.mark_review(source)
                receipt = {'status': 'needs_review', 'reason': str(exc), 'reply': 'Исходная запись сохранена; предложение не опубликовано.'}
            else:
                await client.record_turn(job['device_id'], request, transcript, receipt['reply'])
            records.append({'turn': index, 'transcript': transcript, 'source_id': source,
                            'proposal': note.model_dump(), 'receipt': receipt})
            print(json.dumps(records[-1], ensure_ascii=False), flush=True)
        members = []
        for page in sorted((vault / 'Затея').rglob('*.md')):
            if '/ideas/' in str(page) or '/builds/' in str(page):
                members.append({'path': page.relative_to(vault).as_posix(),
                                'metadata': metadata(page.read_bytes())})
        report = {'vault': str(vault), 'turns': records, 'memberships': members,
                  'semantic_verdict': 'requires_human_review',
                  'review': ['Both travel alternatives share one topic', 'Firmware separate from travel',
                             'No invented release facts or Sichuan destination',
                             'Clarification retains uncertainty and original sources',
                             'Pending/needs_review entries are visible, never claimed saved']}
        (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({'report': str(root / 'report.json'), 'semantic_verdict': report['semantic_verdict'],
                          'memberships': members}, ensure_ascii=False))
        return 2 if any(r['receipt'].get('status') == 'needs_review' for r in records) else 0
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', action='store_true', help='Explicitly allow provider requests and associated cost')
    args = parser.parse_args()
    if not args.real:
        print('No provider called. Pass --real with LLM_BASE_URL, LLM_MODEL and optional LLM_API_KEY.')
        return 0
    return asyncio.run(replay())


if __name__ == '__main__':
    raise SystemExit(main())
