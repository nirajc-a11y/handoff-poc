"""AI engine for LLM-powered customer interactions.

Primary: Sarvam 30B (multilingual, optimized for Indian languages)
Fallback: Groq Llama (if Sarvam unavailable)
Last resort: Mock responses (no API keys configured)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Attempt to import Groq SDK; fall back gracefully if not installed.
try:
    from groq import AsyncGroq  # type: ignore[import-untyped]

    _GROQ_AVAILABLE = True
except ImportError:
    AsyncGroq = None  # type: ignore[assignment,misc]
    _GROQ_AVAILABLE = False


# ---------------------------------------------------------------------------
# Language-specific system prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPTS: dict[str, str] = {
    "en": (
        "You are a professional customer support agent for Demo Corp, a leading technology solutions company. "
        "Your name is Maya. You speak in a warm, friendly, and professional tone.\n\n"
        "IMPORTANT RULES FOR PHONE CONVERSATIONS:\n"
        "- Keep responses SHORT — 1 to 3 sentences maximum. The customer is on a phone call.\n"
        "- Be conversational and natural, like a real person. Don't sound scripted.\n"
        "- Ask one question at a time. Don't overwhelm with multiple questions.\n"
        "- Use simple, clear language. Avoid jargon.\n"
        "- If the customer seems frustrated, acknowledge their feelings first.\n"
        "- If you cannot resolve the issue within 3 exchanges, offer to connect them to a human agent.\n"
        "- Never make up information. If unsure, say you'll check and connect them to a specialist.\n\n"
        "Demo Corp offers: Cloud hosting plans (Basic $29/mo, Pro $79/mo, Enterprise $199/mo), "
        "24/7 technical support, domain registration, SSL certificates, and managed databases.\n\n"
        "Common issues: Password resets, billing disputes, plan upgrades/downgrades, "
        "service outages, DNS configuration, SSL renewal."
    ),
    "mr": (
        "तुम्ही Demo Corp च्या व्यावसायिक ग्राहक सेवा एजंट आहात. तुमचे नाव माया आहे. "
        "तुम्ही उबदार, मैत्रीपूर्ण आणि व्यावसायिक स्वरात बोलता.\n\n"
        "फोन संभाषणासाठी महत्त्वाचे नियम:\n"
        "- उत्तरे लहान ठेवा — जास्तीत जास्त 1 ते 3 वाक्ये. ग्राहक फोनवर आहे.\n"
        "- संभाषणात्मक आणि नैसर्गिक बोला. स्क्रिप्टेड वाटू नका.\n"
        "- एका वेळी एक प्रश्न विचारा.\n"
        "- सोपी, स्पष्ट भाषा वापरा.\n"
        "- जर ग्राहक निराश असेल तर प्रथम त्यांच्या भावना मान्य करा.\n"
        "- जर 3 देवाणघेवाणीत समस्या सोडवता आली नाही तर मानवी एजंटशी जोडण्याची ऑफर द्या.\n"
        "- माहिती बनवू नका. अनिश्चित असल्यास, तज्ञांशी जोडण्याची ऑफर द्या.\n\n"
        "पूर्णपणे मराठीत उत्तर द्या. इंग्रजी शब्द टाळा."
    ),
}


@dataclass
class AIResponse:
    text: str
    confidence: float  # 0.0 to 1.0
    should_escalate: bool
    should_end_call: bool = False
    escalation_reason: str | None = None


class AIEngine:
    """Processes customer messages via Sarvam 30B LLM with keyword-based escalation detection."""

    ESCALATION_KEYWORDS: set[str] = {
        "agent",
        "human",
        "help",
        "speak to someone",
        "representative",
        "operator",
        "real person",
    }

    ESCALATION_KEYWORDS_MR: set[str] = {
        "एजंट",
        "माणूस",
        "मदत",
        "कोणाशी बोलायचं",
        "तक्रार",
        "व्यवस्थापक",
    }

    HANGUP_KEYWORDS: set[str] = {
        "bye",
        "goodbye",
        "good bye",
        "hang up",
        "end call",
        "that's all",
        "that is all",
        "no thanks bye",
        "nothing else",
        "i'm done",
        "no more questions",
        "thanks bye",
        "thank you bye",
        "ok bye",
        "okay bye",
    }

    HANGUP_KEYWORDS_MR: set[str] = {
        "बाय",
        "धन्यवाद बाय",
        "बस्स",
        "एवढंच",
        "काही नाही",
        "ठेवतो",
        "ठेवते",
        "फोन ठेवा",
    }

    SARVAM_BASE = "https://api.sarvam.ai"

    def __init__(self) -> None:
        from app.config import settings

        self.groq_api_key: str = settings.groq_api_key
        self.groq_model: str = settings.groq_model
        self.sarvam_api_key: str = settings.sarvam_api_key
        self.sarvam_model: str = settings.sarvam_llm_model

        # Shared Groq client — reuses TCP+TLS connections across calls
        self._groq_client: AsyncGroq | None = None

        # Circuit breaker: fail fast after consecutive API failures
        self._groq_failures: int = 0
        self._sarvam_failures: int = 0
        self._circuit_breaker_threshold: int = 3  # open circuit after N consecutive failures

    def _get_groq_client(self) -> "AsyncGroq":
        """Lazy-init shared AsyncGroq client for connection reuse."""
        if self._groq_client is None and _GROQ_AVAILABLE and self.groq_api_key:
            self._groq_client = AsyncGroq(api_key=self.groq_api_key)
        return self._groq_client

    def _groq_circuit_open(self) -> bool:
        return self._groq_failures >= self._circuit_breaker_threshold

    def _sarvam_circuit_open(self) -> bool:
        return self._sarvam_failures >= self._circuit_breaker_threshold

    # Regex to strip <think>...</think> blocks from reasoning models
    _THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

    def _get_sarvam_headers(self) -> dict[str, str]:
        return {
            "api-subscription-key": self.sarvam_api_key,
            "Content-Type": "application/json",
        }

    @classmethod
    def _strip_think_tags(cls, text: str) -> str:
        """Remove <think>...</think> reasoning blocks from LLM output."""
        return cls._THINK_RE.sub("", text).strip()

    # ------------------------------------------------------------------
    # Audio transcription (Groq Whisper — kept for batch recording use)
    # ------------------------------------------------------------------

    async def transcribe_audio(self, audio_url: str, audio_data: bytes | None = None) -> str:
        """Transcribe audio via Groq Whisper.

        Args:
            audio_url: URL to download audio from (used only if audio_data is None)
            audio_data: Pre-downloaded audio bytes (avoids a second HTTP download)
        """
        if not self.groq_api_key or not _GROQ_AVAILABLE:
            logger.warning("Groq not available for transcription")
            return ""

        try:
            if audio_data is None:
                async with httpx.AsyncClient(timeout=15.0) as http_client:
                    resp = await http_client.get(audio_url)
                    resp.raise_for_status()
                    audio_data = resp.content

            if len(audio_data) < 1000:
                logger.info("Audio too small (%d bytes), skipping transcription", len(audio_data))
                return ""

            groq_client = self._get_groq_client()
            transcription = await groq_client.audio.transcriptions.create(
                file=("recording.mp3", audio_data),
                model="whisper-large-v3-turbo",
            )
            text = transcription.text.strip()
            logger.info("Transcribed audio (%d bytes): %s", len(audio_data), text[:100])
            return text

        except Exception:
            logger.exception("Audio transcription failed")
            return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_message(
        self,
        customer_message: str,
        conversation_history: list[dict],
        system_prompt: str | None = None,
        confidence_threshold: float = 0.3,
        max_turns: int = 10,
        language: str = "en",
        company_name: str = "Demo Corp",
    ) -> AIResponse:
        """Process a customer message and return an AI response.

        Checks for escalation keywords first, then delegates to Sarvam 30B
        (or Groq / mock fallback), and finally checks turn limits.
        """
        keywords = self.ESCALATION_KEYWORDS_MR if language == "mr" else self.ESCALATION_KEYWORDS

        if system_prompt is None:
            system_prompt = SYSTEM_PROMPTS.get(language, SYSTEM_PROMPTS["en"])

        # 1. Check for explicit escalation keywords
        message_lower = customer_message.lower()
        for keyword in keywords:
            if keyword in message_lower:
                escalation_text = (
                    "मला समजले की तुम्हाला मानवी एजंटशी बोलायचे आहे. मी तुम्हाला आता जोडतो."
                    if language == "mr"
                    else "I understand you'd like to speak with a human agent. Let me transfer you now."
                )
                return AIResponse(
                    text=escalation_text,
                    confidence=1.0,
                    should_escalate=True,
                    escalation_reason=f"customer_requested: '{keyword}'",
                )

        # 1b. Check for hangup / goodbye keywords
        hangup_kw = self.HANGUP_KEYWORDS_MR if language == "mr" else self.HANGUP_KEYWORDS
        for keyword in hangup_kw:
            if keyword in message_lower:
                farewell_text = (
                    f"{company_name} शी संपर्क केल्याबद्दल धन्यवाद. तुमचा दिवस चांगला जावो!"
                    if language == "mr"
                    else f"Thank you for calling {company_name}. Have a great day! Goodbye."
                )
                return AIResponse(
                    text=farewell_text,
                    confidence=1.0,
                    should_escalate=False,
                    should_end_call=True,
                )

        # 2. Turn count
        turn_count = len(conversation_history) // 2

        # 3. Call LLM: Groq primary (fast TTFT, no reasoning overhead),
        #    Sarvam fallback, mock last resort
        text, confidence = None, 0.85
        if self.groq_api_key and _GROQ_AVAILABLE:
            try:
                text, confidence = await self._call_groq(system_prompt, conversation_history, customer_message)
            except Exception:
                logger.exception("Groq LLM failed; trying Sarvam fallback")

        if text is None and self.sarvam_api_key:
            try:
                text, confidence = await self._call_sarvam(system_prompt, conversation_history, customer_message)
            except Exception:
                logger.exception("Sarvam LLM also failed; using mock response")

        if text is None:
            return self._mock_response(customer_message, turn_count, language)

        # 4. Check turn limit
        if turn_count >= max_turns:
            return AIResponse(
                text=text,
                confidence=min(confidence, 0.3),
                should_escalate=True,
                escalation_reason="max_turns_exceeded",
            )

        # 5. Confidence-based escalation
        should_escalate = confidence < confidence_threshold
        escalation_reason = f"low_confidence ({confidence:.2f})" if should_escalate else None

        return AIResponse(
            text=text,
            confidence=confidence,
            should_escalate=should_escalate,
            escalation_reason=escalation_reason,
        )

    # ------------------------------------------------------------------
    # Sarvam 30B integration
    # ------------------------------------------------------------------

    async def _call_sarvam(
        self,
        system_prompt: str,
        history: list[dict],
        message: str,
    ) -> tuple[str, float]:
        """Call Sarvam chat completion API (OpenAI-compatible)."""
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": message})

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            resp = await client.post(
                f"{self.SARVAM_BASE}/v1/chat/completions",
                headers=self._get_sarvam_headers(),
                json={
                    "model": self.sarvam_model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 150,
                },
            )
            if resp.status_code >= 400:
                logger.error("Sarvam LLM error %d: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()

        result = resp.json()
        text = (result["choices"][0]["message"]["content"] or "").strip()
        text = self._strip_think_tags(text)
        logger.info("Sarvam LLM: %s", text[:100])
        return text, 0.85

    async def _call_sarvam_stream(
        self,
        system_prompt: str,
        history: list[dict],
        message: str,
    ):
        """Stream Sarvam chat completion, yielding sentences as they complete.

        Skips <think>...</think> reasoning blocks from the stream.
        Yields text at sentence boundaries (. ! ?) so TTS can start on
        the first sentence while the LLM generates the rest.
        """
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": message})

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
            async with client.stream(
                "POST",
                f"{self.SARVAM_BASE}/v1/chat/completions",
                headers=self._get_sarvam_headers(),
                json={
                    "model": self.sarvam_model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 150,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    logger.error("Sarvam LLM stream error %d: %s", resp.status_code, body[:500])
                    resp.raise_for_status()

                buffer = ""
                in_think_block = False  # Track <think> blocks to skip reasoning
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}).get("content") or ""
                    if not delta:
                        continue

                    # Skip <think>...</think> reasoning blocks
                    if in_think_block:
                        if "</think>" in delta:
                            # End of think block — keep text after closing tag
                            delta = delta.split("</think>", 1)[1]
                            in_think_block = False
                            if not delta:
                                continue
                        else:
                            continue  # Still inside think block, skip
                    if "<think>" in delta:
                        # Start of think block — keep text before opening tag
                        before, _, after = delta.partition("<think>")
                        if before:
                            buffer += before
                        if "</think>" in after:
                            # Think block opened and closed in same chunk
                            delta = after.split("</think>", 1)[1]
                            if not delta:
                                continue
                            buffer += delta
                        else:
                            in_think_block = True
                            continue
                    else:
                        buffer += delta

                    # Yield complete sentences
                    while True:
                        best_idx = -1
                        for sep in [". ", "! ", "? ", ".\n", "!\n", "?\n"]:
                            idx = buffer.find(sep)
                            if idx != -1 and (best_idx == -1 or idx < best_idx):
                                best_idx = idx
                        if best_idx != -1:
                            sentence = buffer[:best_idx + 2].strip()
                            buffer = buffer[best_idx + 2:]
                            if sentence:
                                yield sentence
                        else:
                            break

                # Yield remaining text (strip any residual think tags)
                remaining = self._strip_think_tags(buffer)
                if remaining:
                    yield remaining

    # ------------------------------------------------------------------
    # Groq integration (fallback)
    # ------------------------------------------------------------------

    async def _call_groq(
        self,
        system_prompt: str,
        history: list[dict],
        message: str,
    ) -> tuple[str, float]:
        """Call the Groq chat completion API (fallback)."""
        client = self._get_groq_client()

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": message})

        completion = await client.chat.completions.create(
            model=self.groq_model,
            messages=messages,
            temperature=0.7,
            max_tokens=150,
        )

        text = (completion.choices[0].message.content or "").strip()
        return text, 0.85

    async def _call_groq_stream(
        self,
        system_prompt: str,
        history: list[dict],
        message: str,
    ):
        """Stream Groq chat completion (fallback), yielding sentences."""
        client = self._get_groq_client()

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": message})

        stream = await client.chat.completions.create(
            model=self.groq_model,
            messages=messages,
            temperature=0.7,
            max_tokens=80,
            stream=True,
        )

        buffer = ""
        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            buffer += delta
            while True:
                best_idx = -1
                for sep in [". ", "! ", "? ", ".\n", "!\n", "?\n"]:
                    idx = buffer.find(sep)
                    if idx != -1 and (best_idx == -1 or idx < best_idx):
                        best_idx = idx
                if best_idx != -1:
                    sentence = buffer[:best_idx + 2].strip()
                    buffer = buffer[best_idx + 2:]
                    if sentence:
                        yield sentence
                else:
                    break
        if buffer.strip():
            yield buffer.strip()

    # ------------------------------------------------------------------
    # Streaming public API
    # ------------------------------------------------------------------

    async def process_message_stream(
        self,
        customer_message: str,
        conversation_history: list[dict],
        language: str = "en",
        system_prompt: str | None = None,
        company_name: str = "Demo Corp",
    ):
        """Like process_message but yields (sentence, metadata) tuples.

        First checks keywords (escalation/hangup) and yields immediately.
        Then streams LLM sentences as they're generated.

        Yields: (sentence_text, AIResponse_or_None)
            - For keyword matches: (text, AIResponse) — single yield
            - For LLM sentences: (sentence, None) — multiple yields
        """
        # Check escalation keywords
        keywords = self.ESCALATION_KEYWORDS_MR if language == "mr" else self.ESCALATION_KEYWORDS
        message_lower = customer_message.lower()
        for keyword in keywords:
            if keyword in message_lower:
                escalation_text = (
                    "मला समजले की तुम्हाला मानवी एजंटशी बोलायचे आहे. मी तुम्हाला आता जोडतो."
                    if language == "mr"
                    else "I understand you'd like to speak with a human agent. Let me transfer you now."
                )
                yield escalation_text, AIResponse(
                    text=escalation_text, confidence=1.0,
                    should_escalate=True, escalation_reason=f"customer_requested: '{keyword}'",
                )
                return

        # Check hangup keywords
        hangup_kw = self.HANGUP_KEYWORDS_MR if language == "mr" else self.HANGUP_KEYWORDS
        for keyword in hangup_kw:
            if keyword in message_lower:
                farewell_text = (
                    f"{company_name} शी संपर्क केल्याबद्दल धन्यवाद. तुमचा दिवस चांगला जावो!"
                    if language == "mr"
                    else f"Thank you for calling {company_name}. Have a great day! Goodbye."
                )
                yield farewell_text, AIResponse(
                    text=farewell_text, confidence=1.0,
                    should_escalate=False, should_end_call=True,
                )
                return

        # Stream LLM: Groq primary (fast), Sarvam fallback, with circuit breaker
        if system_prompt is None:
            system_prompt = SYSTEM_PROMPTS.get(language, SYSTEM_PROMPTS["en"])

        if self.groq_api_key and _GROQ_AVAILABLE and not self._groq_circuit_open():
            try:
                async for sentence in self._call_groq_stream(
                    system_prompt, conversation_history, customer_message
                ):
                    yield sentence, None
                self._groq_failures = 0  # reset on success
                return
            except Exception:
                self._groq_failures += 1
                logger.exception(
                    "Groq streaming failed (failures=%d/%d); trying Sarvam fallback",
                    self._groq_failures, self._circuit_breaker_threshold,
                )
        elif self._groq_circuit_open():
            logger.warning("Groq circuit breaker OPEN (%d failures), skipping", self._groq_failures)

        if self.sarvam_api_key and not self._sarvam_circuit_open():
            try:
                async for sentence in self._call_sarvam_stream(
                    system_prompt, conversation_history, customer_message
                ):
                    yield sentence, None
                self._sarvam_failures = 0  # reset on success
                return
            except Exception:
                self._sarvam_failures += 1
                logger.exception(
                    "Sarvam LLM streaming failed (failures=%d/%d); using mock",
                    self._sarvam_failures, self._circuit_breaker_threshold,
                )

        turn_count = len(conversation_history) // 2
        resp = self._mock_response(customer_message, turn_count, language)
        yield resp.text, resp

    # ------------------------------------------------------------------
    # Mock fallback
    # ------------------------------------------------------------------

    def _mock_response(self, message: str, turn_count: int, language: str = "en") -> AIResponse:
        """Template-based responses that gradually lose confidence as turns increase."""
        if turn_count <= 3:
            text = (
                "संपर्क केल्याबद्दल धन्यवाद! मी तुम्हाला यासाठी मदत करण्यास आनंदित आहे. "
                "कृपया मला अधिक तपशील द्या जेणेकरून मी तुम्हाला अधिक चांगल्या प्रकारे मदत करू शकेन."
                if language == "mr"
                else
                "Thank you for reaching out! I'd be happy to help you with that. "
                "Could you please provide me with a few more details so I can assist you better?"
            )
            return AIResponse(
                text=text,
                confidence=0.9,
                should_escalate=False,
            )

        if turn_count <= 6:
            text = (
                "अतिरिक्त माहितीबद्दल धन्यवाद. मी तुमच्यासाठी हे तपासतो. "
                "तुम्ही शेअर केलेल्या माहितीच्या आधारे, मी हे सुचवू शकतो..."
                if language == "mr"
                else
                "I appreciate the additional information. Let me look into this for you. "
                "Based on what you've shared, here's what I can suggest..."
            )
            return AIResponse(
                text=text,
                confidence=0.8,
                should_escalate=False,
            )

        if turn_count <= 9:
            text = (
                "मी तुमच्या समस्येवर काम करत आहे. एक क्षण थांबा."
                if language == "mr"
                else
                "I'm still working on your issue. Please bear with me for a moment."
            )
            return AIResponse(
                text=text,
                confidence=0.7,
                should_escalate=False,
            )

        # Turn 10+: turn limit reached, escalate
        text = (
            "तुम्हाला सर्वोत्तम मदत मिळावी अशी माझी इच्छा आहे. "
            "तुम्हाला एका तज्ञाशी जोडणे चांगले होईल जे तुम्हाला अधिक संपूर्ण मदत करू शकतील. "
            "तुम्हाला मानवी एजंटकडे पाठवू का?"
            if language == "mr"
            else
            "I want to make sure you get the best possible help. "
            "It might be best to connect you with a specialist who can assist you more thoroughly. "
            "Would you like me to transfer you to a human agent?"
        )
        return AIResponse(
            text=text,
            confidence=0.5,
            should_escalate=True,
            escalation_reason="turn_limit_reached",
        )


# Module-level singleton
ai_engine = AIEngine()
