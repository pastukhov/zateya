from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WikiPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(pattern=r"^wiki/(concepts|entities|syntheses)/[a-z0-9][a-z0-9-]{0,79}\.md$")
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)
    sources: list[str] = Field(min_length=1, max_length=100)


class Organization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic_path: str | None = Field(default=None, pattern=r"^wiki/concepts/[a-z0-9][a-z0-9-]{0,79}\.md$")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    membership: bool = True
    rename: bool = False


class KnowledgeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["capture", "amend", "query", "plan", "build", "organize"]
    organization: Organization | None = None
    evidence_sources: list[str] = Field(default_factory=list, max_length=100)
    target_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    pages: list[WikiPage] = Field(default_factory=list, max_length=12)
