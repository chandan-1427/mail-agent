from pydantic import BaseModel, Field


class FieldDefinition(BaseModel):
    name: str = Field(description="Lowercase, no spaces. e.g. 'years_experience'")
    description: str = Field(description="Human-readable label shown to the candidate")
    field_type: str = Field(description="One of: url, file, text, email, phone")


class RequirementCreate(BaseModel):
    required_fields: list[FieldDefinition] = Field(min_length=1)