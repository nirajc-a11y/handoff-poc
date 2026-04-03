"""LiveKit LLM plugin wrapping the existing AIEngine (Groq/Sarvam).

Preserves: conversation history, system prompts, escalation keyword
detection, end-call detection, and confidence scoring. Streams
sentences via process_message_stream().
"""

from __future__ import annotations

import logging
from uuid import uuid4

from livekit.agents import llm, APIConnectOptions

from app.core.ai_engine import ai_engine, SYSTEM_PROMPTS

logger = logging.getLogger(__name__)


class SarvamLLM(llm.LLM):
    """LiveKit-compatible LLM plugin backed by AIEngine (Groq/Sarvam)."""

    def __init__(
        self,
        *,
        language: str = "en",
        company_name: str = "Demo Corp",
        system_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self._language = language
        self._company_name = company_name
        self._system_prompt = system_prompt or SYSTEM_PROMPTS.get(language, SYSTEM_PROMPTS["en"])
        self._history: list[dict] = []
        self._should_escalate = False
        self._should_end_call = False
        self._escalation_reason: str | None = None
        self._supervisor_hints: list[str] = []

    @property
    def should_escalate(self) -> bool:
        return self._should_escalate

    @property
    def should_end_call(self) -> bool:
        return self._should_end_call

    def inject_system_hint(self, hint: str) -> None:
        """Inject a supervisor whisper hint for the next LLM turn."""
        self._supervisor_hints.append(hint)

    def chat(self, *, chat_ctx: llm.ChatContext, **kwargs) -> "SarvamLLMStream":
        # Extract the latest user message
        user_message = ""
        for item in reversed(chat_ctx.items):
            if hasattr(item, "role") and item.role == "user":
                user_message = item.text_content or ""
                break

        conn_options = kwargs.get("conn_options") or APIConnectOptions()
        tools = kwargs.get("tools") or []

        return SarvamLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools,
            conn_options=conn_options,
            user_message=user_message,
        )


class SarvamLLMStream(llm.LLMStream):
    """Async stream that yields ChatChunk objects from AIEngine."""

    def __init__(
        self,
        llm_instance: SarvamLLM,
        *,
        chat_ctx: llm.ChatContext,
        tools: list,
        conn_options,
        user_message: str,
    ) -> None:
        super().__init__(llm_instance, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._llm_instance = llm_instance
        self._user_message = user_message

    async def _run(self) -> None:
        if not self._user_message.strip():
            return

        # Build effective system prompt (include supervisor hints if any)
        system_prompt = self._llm_instance._system_prompt
        if self._llm_instance._supervisor_hints:
            hints = "\n".join(
                f"[Supervisor guidance]: {h}" for h in self._llm_instance._supervisor_hints
            )
            system_prompt = f"{system_prompt}\n\n{hints}"
            self._llm_instance._supervisor_hints.clear()

        full_response = ""
        async for sentence, metadata in ai_engine.process_message_stream(
            customer_message=self._user_message,
            conversation_history=self._llm_instance._history,
            language=self._llm_instance._language,
            system_prompt=system_prompt,
            company_name=self._llm_instance._company_name,
        ):
            full_response += sentence + " "

            if metadata is not None:
                self._llm_instance._should_escalate = metadata.should_escalate
                self._llm_instance._should_end_call = metadata.should_end_call
                self._llm_instance._escalation_reason = metadata.escalation_reason

            self._event_ch.send_nowait(
                llm.ChatChunk(
                    id=str(uuid4()),
                    delta=llm.ChoiceDelta(role="assistant", content=sentence),
                )
            )

        # Update conversation history
        self._llm_instance._history.append({"role": "user", "content": self._user_message})
        self._llm_instance._history.append({"role": "assistant", "content": full_response.strip()})

        # Keep history bounded
        if len(self._llm_instance._history) > 20:
            self._llm_instance._history = self._llm_instance._history[-20:]
