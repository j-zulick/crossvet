"""Configuration management for the Open Deep Research system."""

import os
from enum import Enum
from typing import Any, List

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field


class SearchAPI(Enum):
    """Enumeration of available search API providers."""
    
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    TAVILY = "tavily"
    GATEWAY = "gateway"
    NONE = "none"

class MCPConfig(BaseModel):
    """Configuration for Model Context Protocol (MCP) servers."""
    
    url: str | None = Field(
        default=None,
    )
    """The URL of the MCP server"""
    tools: List[str] | None = Field(
        default=None,
    )
    """The tools to make available to the LLM"""
    auth_required: bool | None = Field(
        default=False,
    )
    """Whether the MCP server requires authentication"""

class Configuration(BaseModel):
    """Main configuration class for the Deep Research agent."""
    
    # General Configuration
    max_structured_output_retries: int = Field(
        default=3,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 3,
                "min": 1,
                "max": 10,
                "description": "Maximum number of retries for structured output calls from models"
            }
        }
    )
    allow_clarification: bool = Field(
        default=True,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "boolean",
                "default": True,
                "description": "Whether to allow the researcher to ask the user clarifying questions before starting research"
            }
        }
    )
    max_concurrent_research_units: int = Field(
        default=5,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 5,
                "min": 1,
                "max": 20,
                "step": 1,
                "description": "Maximum number of research units to run concurrently. This will allow the researcher to use multiple sub-agents to conduct research. Note: with more concurrency, you may run into rate limits."
            }
        }
    )
    # Research Configuration
    search_api: SearchAPI = Field(
        default=SearchAPI.TAVILY,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "select",
                "default": "tavily",
                "description": "Search API to use for research. NOTE: Make sure your Researcher Model supports the selected search API.",
                "options": [
                    {"label": "Tavily", "value": SearchAPI.TAVILY.value},
                    {"label": "Self-hosted research gateway (MCP)", "value": SearchAPI.GATEWAY.value},
                    {"label": "OpenAI Native Web Search", "value": SearchAPI.OPENAI.value},
                    {"label": "Anthropic Native Web Search", "value": SearchAPI.ANTHROPIC.value},
                    {"label": "None", "value": SearchAPI.NONE.value}
                ]
            }
        }
    )
    search_also: str = Field(
        default="",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "select",
                "default": "",
                "description": "Also give researchers a model's built-in web search next to the main search (e.g. your gateway plus OpenAI search). The researcher model must be from the same vendor.",
                "options": [
                    {"label": "None", "value": ""},
                    {"label": "OpenAI built-in web search", "value": "openai"},
                    {"label": "Anthropic built-in web search", "value": "anthropic"}
                ]
            }
        }
    )
    max_researcher_iterations: int = Field(
        default=6,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 6,
                "min": 1,
                "max": 10,
                "step": 1,
                "description": "Maximum number of research iterations for the Research Supervisor. This is the number of times the Research Supervisor will reflect on the research and ask follow-up questions."
            }
        }
    )
    max_react_tool_calls: int = Field(
        default=10,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 10,
                "min": 1,
                "max": 30,
                "step": 1,
                "description": "Maximum number of tool calling iterations to make in a single researcher step."
            }
        }
    )
    # Model Configuration
    summarization_model: str = Field(
        default="openai:gpt-4.1-mini",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "openai:gpt-4.1-mini",
                "description": "Model for summarizing research results from Tavily search results"
            }
        }
    )
    summarization_model_max_tokens: int = Field(
        default=8192,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 8192,
                "description": "Maximum output tokens for summarization model"
            }
        }
    )
    max_content_length: int = Field(
        default=50000,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 50000,
                "min": 1000,
                "max": 200000,
                "description": "Maximum character length for webpage content before summarization"
            }
        }
    )
    research_model: str = Field(
        default="openai:gpt-4.1",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "openai:gpt-4.1",
                "description": "Model for conducting research. NOTE: Make sure your Researcher Model supports the selected search API."
            }
        }
    )
    research_model_max_tokens: int = Field(
        default=10000,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 10000,
                "description": "Maximum output tokens for research model"
            }
        }
    )
    supervisor_model: str = Field(
        default="",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "",
                "description": "Orchestration: the model that plans sub-questions, delegates them to researchers and decides when research is done. Must support tool calls. Empty = the research model."
            }
        }
    )
    researcher_model: str = Field(
        default="",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "",
                "description": "Research: the model that searches, calls tools and reads sources for each sub-question. Must support tool calls and the selected search API. Empty = the research model."
            }
        }
    )
    compression_model: str = Field(
        default="openai:gpt-4.1",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "openai:gpt-4.1",
                "description": "Model for compressing research findings from sub-agents. NOTE: Make sure your Compression Model supports the selected search API."
            }
        }
    )
    compression_model_max_tokens: int = Field(
        default=8192,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 8192,
                "description": "Maximum output tokens for compression model"
            }
        }
    )
    final_report_model: str = Field(
        default="openai:gpt-4.1",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "openai:gpt-4.1",
                "description": "Model for writing the final report from all research findings"
            }
        }
    )
    final_report_model_max_tokens: int = Field(
        default=10000,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 10000,
                "description": "Maximum output tokens for final report model"
            }
        }
    )
    # MCP server configuration
    mcp_config: MCPConfig | None = Field(
        default=None,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "mcp",
                "description": "MCP server configuration"
            }
        }
    )
    require_approval: bool = Field(
        default=False,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "boolean",
                "default": False,
                "description": "Pause after research so a person can approve, steer or reject the final report before it is written."
            }
        }
    )
    # Cross-vendor review council (runs after the draft report)
    cross_vendor_review_enabled: bool = Field(
        default=False,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "boolean",
                "default": False,
                "description": "Have a council of models from different vendors critique the draft report, vote on the critiques, and revise it."
            }
        }
    )
    review_models: str = Field(
        default="",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "",
                "description": "Comma-separated reviewer models, e.g. openai:gpt-5.5,anthropic:claude-sonnet-5-5 or openrouter:<model>; `crossvet-setup` picks them from the models your keys can use. At least two required."
            }
        }
    )
    review_support_checker: str = Field(
        default="",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "select",
                "default": "",
                "options": [{"label": "Off (quote check only)", "value": ""}, {"label": "Jev (TypeSafe)", "value": "jev"}],
                "description": "Also check that a quoted passage supports the claim made from it: position changes, AGREE / BUILD_ON verdicts, blind-pass points. 'jev' needs TYPESAFE_API_KEY."
            }
        }
    )
    review_support_model: str = Field(
        default="",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "",
                "description": "Jev model id, e.g. jev-1.14.0 to pin a version (default: TYPESAFE_DEFAULT_MODEL, else jev-latest)."
            }
        }
    )
    review_support_min_prob: float = Field(
        default=0.5,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 0.5,
                "min": 0.1,
                "max": 0.95,
                "step": 0.05,
                "description": "A passage whose support probability is below this does not count as evidence for the claim."
            }
        }
    )
    review_fallback_models: str = Field(
        default="",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "",
                "description": "Comma-separated spare reviewer models. When a reviewer fails, the next spare (preferring a vendor not already on the panel) takes its place; the Review notes say who replaced whom."
            }
        }
    )
    review_call_timeout: float = Field(
        default=0,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 0,
                "description": "Seconds before a single review call (outline, critique, critic, deliberation, vote, revision) is abandoned and handled as a failure. 0 = no limit."
            }
        }
    )
    review_reviser_model: str = Field(
        default="",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "",
                "description": "Model that revises the report after review. Defaults to the final report model. Pick one from a vendor that is not on the review panel so no lab grades and rewrites its own work."
            }
        }
    )
    review_critic_enabled: bool = Field(
        default=True,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "boolean",
                "default": True,
                "description": "Before voting, have an independent critic check each reviewer finding against the research notes (agree / disagree with evidence / disagree concern). Unresolved findings are reported as disputed."
            }
        }
    )
    review_blind_pass_enabled: bool = Field(
        default=False,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "boolean",
                "default": False,
                "description": "Before reading the draft, each reviewer outlines the answer from the research notes alone. Grounded points the draft omits are added to the feedback (one short extra call per reviewer)."
            }
        }
    )
    review_blind_max_points: int = Field(
        default=6,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 6,
                "description": "Points per blind outline."
            }
        }
    )
    review_blind_max_tokens: int = Field(
        default=1500,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 1500,
                "description": "Maximum output tokens for a blind outline (keeps the extra call cheap; reasoning models count their thinking against it)."
            }
        }
    )
    review_deliberation_rounds: int = Field(
        default=0,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 0,
                "min": 0,
                "max": 3,
                "step": 1,
                "description": "Deliberation rounds before voting (0 = off). Each round a rotating challenger contests findings and the author answers; a change of position counts only with a passage from the research notes, and ungrounded changes are flagged as possible sycophancy."
            }
        }
    )
    review_deliberation_early_stop: bool = Field(
        default=True,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "boolean",
                "default": True,
                "description": "Stop deliberation before the round cap when code finds consensus (no finding moved and challengers endorse enough findings) or a stable disagreement (nothing moved for two rounds). Off: stop only when nobody contests anything."
            }
        }
    )
    review_consensus_threshold: float = Field(
        default=1.0,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 1.0,
                "min": 0.5,
                "max": 1.0,
                "step": 0.05,
                "description": "Share of findings the challengers must endorse (AGREE) in a round with no changes for deliberation to stop early. 1.0 = unanimous."
            }
        }
    )
    review_deliberation_min_rounds: int = Field(
        default=1,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 1,
                "min": 1,
                "max": 3,
                "step": 1,
                "description": "Deliberation never stops early before this round."
            }
        }
    )
    review_consensus_min_grounded_share: float = Field(
        default=0.5,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "slider",
                "default": 0.5,
                "min": 0.0,
                "max": 1.0,
                "step": 0.1,
                "description": "False-consensus guard: if fewer endorsements than this share cite a passage found in the notes (or the challengers were silent), one more round runs with the next challenger before stopping. 0 = guard off."
            }
        }
    )
    run_export_path: str = Field(
        default="",
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "default": "",
                "description": "Optional JSONL file to append each reviewed run to (draft, critiques, critic verdicts, ballots, revision) for evaluation or fine-tuning."
            }
        }
    )
    review_model_max_tokens: int = Field(
        default=8000,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "number",
                "default": 8000,
                "description": "Maximum output tokens per reviewer call (reasoning models count their thinking against this limit)"
            }
        }
    )
    mcp_prompt: str | None = Field(
        default=None,
        json_schema_extra={
            "x_oap_ui_config": {
                "type": "text",
                "description": "Any additional instructions to pass along to the Agent regarding the MCP tools that are available to it."
            }
        }
    )


    def model_for(self, role: str) -> str:
        """Model for a pipeline role; the orchestration and research roles fall back to ``research_model``."""
        if role == "supervisor":
            return self.supervisor_model or self.research_model
        if role == "researcher":
            return self.researcher_model or self.research_model
        return {
            "summarization": self.summarization_model,
            "compression": self.compression_model,
            "final_report": self.final_report_model,
        }.get(role, self.research_model)

    @classmethod
    def from_runnable_config(
        cls, config: RunnableConfig | None = None
    ) -> "Configuration":
        """Create a Configuration instance from a RunnableConfig."""
        configurable = config.get("configurable", {}) if config else {}
        field_names = list(cls.model_fields.keys())
        values: dict[str, Any] = {
            # An empty environment variable (e.g. "RESEARCH_MODEL=") means "use the default".
            field_name: os.environ.get(field_name.upper()) or configurable.get(field_name)
            for field_name in field_names
        }
        return cls(**{k: v for k, v in values.items() if v not in (None, "")})

    model_config = ConfigDict(arbitrary_types_allowed=True)