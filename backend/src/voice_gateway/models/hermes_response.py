"""Hermes stage data models (ТЗ section 22).

The logical JSON contract Hermes must return:

    {
      "reply": "string",
      "note": {
        "create": true,
        "title": "string",
        "content": "markdown",
        "tags": ["tag1", "tag2"]
      }
    }

``reply`` is always required. ``note`` defaults to "no note" when absent.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from backend.src.voice_gateway.knowledge.models import KnowledgeProposal


class HermesNote(BaseModel):
    """Optional note request carried in the Hermes structured response."""

    knowledge: KnowledgeProposal | None = None
    create: bool = False
    title: str = ""
    content: str = ""
    tags: list[str] = Field(default_factory=list)


class Clarification(BaseModel):
    question: str = Field(min_length=1, max_length=400)
    source_ids: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(min_length=1, max_length=8)


class DialogueResolution(BaseModel):
    question_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    action: Literal["answered", "declined", "superseded"]


class AnswerCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str | None = Field(default=None,min_length=1,max_length=64)
    path: str = Field(default="",max_length=512)
    title: str = Field(default="", max_length=200)
    quote: str = Field(default="",max_length=600)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["found", "not_found", "ambiguous", "conflicting"]
    citations: list[AnswerCitation] = Field(default_factory=list, max_length=8)


class HermesResponse(BaseModel):
    """Validated structured Hermes result (ТЗ section 22)."""

    reply: str
    note: HermesNote = Field(default_factory=HermesNote)
    clarification: Clarification | None = None
    dialogue_resolution: DialogueResolution | None = None
    answer: GroundedAnswer | None = None
