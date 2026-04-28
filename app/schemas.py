"""
Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, Field


class FieldDefinition(BaseModel):
    """Definition of a required field."""
    name: str = Field(description="Lowercase, no spaces. e.g. 'linkedin', 'years_experience'")
    description: str = Field(description="Human-readable description. e.g. 'Your LinkedIn profile URL'")
    field_type: str = Field(description="One of: url, file, text, email, phone")


class RequirementCreate(BaseModel):
    """Schema for creating/updating requirements."""
    required_fields: list[FieldDefinition] = Field(min_length=1)


class TriageResult(BaseModel):
    """Result of the triage process."""
    is_approved: bool
    extracted_data: dict
    missing_fields: list[str]
    reply_draft: str | None


class ExtractedField(BaseModel):
    """Extracted field with confidence scoring."""
    value: str
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    source: str = Field(description="Where this came from: email_body, resume, cover_letter, etc.")


class EmailParserResult(BaseModel):
    """Result of email parsing."""
    extracted_data: dict[str, ExtractedField]
    summary: str
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class TriageDecision(BaseModel):
    """Decision made by the triage agent."""
    is_approved: bool
    missing_fields: list[str]
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
