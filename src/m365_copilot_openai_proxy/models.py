from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContentPart(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    text: str | None = None


class ToolFunction(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = "function"
    function: ToolFunction


class ToolCallFunction(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    arguments: str


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: str = "function"
    function: ToolCallFunction


class OpenAIMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class OpenAIChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[OpenAIMessage]
    stream: bool = False
    temperature: float | None = None
    user: str | None = None
    tools: list[ToolDefinition] | None = None
    tool_choice: str | dict[str, Any] | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    n: int | None = None
    stop: str | list[str] | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None


class AnthropicMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["user", "assistant"]
    content: str | list[ContentPart]


class AnthropicMessagesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[AnthropicMessage]
    system: str | list[ContentPart] | None = None
    stream: bool = False
    max_tokens: int | None = None
    temperature: float | None = None


class CopilotMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    text: str = ""
    attributions: list[dict[str, Any]] = Field(default_factory=list)


class CopilotConversation(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    messages: list[CopilotMessage] = Field(default_factory=list)


class OpenAIResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    input: str | list[Any]
    instructions: str | None = None
    stream: bool = False
    previous_response_id: str | None = None
    user: str | None = None


class ImageData(BaseModel):
    """A single inbound image extracted from multimodal message content.

    base64 is raw base64 (no data: prefix); media_type is e.g. "image/png".
    For remote images the client only sends an http(s) ``url``; base64 is then
    empty at extraction time and filled in later by downloading the url (see
    SubstrateCopilotClient._upload_images). Exactly one of base64/url is set.
    """
    model_config = ConfigDict(extra="allow")

    base64: str = ""
    media_type: str = "image/png"
    file_name: str = "upload.png"
    url: str = ""


class TranslatedRequest(BaseModel):
    prompt: str
    additional_context: list[str] = Field(default_factory=list)
    images: list[ImageData] = Field(default_factory=list)
