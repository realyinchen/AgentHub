"""Schema for title generation endpoint."""

from pydantic import BaseModel, Field


class TitleGenerateRequest(BaseModel):
    """Request for generating a conversation title."""

    user_message: str = Field(
        description="The user's message to generate title from",
        examples=["What is the weather in Beijing?"],
    )
    ai_response: str | None = Field(
        default=None,
        description="The AI's response (optional, for better context)",
        examples=["The weather in Beijing is sunny, 25°C."],
    )


class TitleGenerateResponse(BaseModel):
    """Response for title generation."""

    title: str = Field(
        description="The generated title",
        examples=["Beijing Weather Inquiry"],
    )
