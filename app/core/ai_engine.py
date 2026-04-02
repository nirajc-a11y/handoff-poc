"""AI engine for LLM-powered customer interactions with Groq inference and mock fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass

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
    escalation_reason: str | None = None


class AIEngine:
    """Processes customer messages via Groq LLM with keyword-based escalation detection."""

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

    def __init__(self) -> None:
        from app.config import settings

        self.groq_api_key: str = settings.groq_api_key
        self.default_model: str = settings.groq_model

    # ------------------------------------------------------------------
    # Audio transcription
    # ------------------------------------------------------------------

    async def transcribe_audio(self, audio_url: str) -> str:
        """Download audio from URL and transcribe via Groq Whisper."""
        if not self.groq_api_key or not _GROQ_AVAILABLE:
            logger.warning("Groq not available for transcription")
            return ""

        import httpx

        try:
            # Download the recording from Plivo
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                resp = await http_client.get(audio_url)
                resp.raise_for_status()
                audio_data = resp.content

            if len(audio_data) < 1000:
                # Too small — likely silence or error
                logger.info("Audio too small (%d bytes), skipping transcription", len(audio_data))
                return ""

            # Send to Groq Whisper
            groq_client = AsyncGroq(api_key=self.groq_api_key)
            transcription = await groq_client.audio.transcriptions.create(
                file=("recording.mp3", audio_data),
                model="whisper-large-v3",
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
        conversation_history: list[dict],  # [{"role": "user"/"assistant", "content": "..."}]
        system_prompt: str | None = None,
        confidence_threshold: float = 0.3,
        max_turns: int = 10,
        language: str = "en",
    ) -> AIResponse:
        """Process a customer message and return an AI response.

        Checks for escalation keywords first, then delegates to Groq (or mock
        fallback), and finally checks whether the turn limit has been exceeded.

        Parameters
        ----------
        language:
            ``"en"`` for English (default) or ``"mr"`` for Marathi.
        """
        # Select language-specific escalation keywords
        keywords = self.ESCALATION_KEYWORDS_MR if language == "mr" else self.ESCALATION_KEYWORDS

        # Use language-specific system prompt when none is provided
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

        # 2. Determine turn count (each user+assistant pair counts as one turn)
        turn_count = len(conversation_history) // 2

        # 3. Generate a response via Groq or the mock fallback
        if self.groq_api_key and _GROQ_AVAILABLE:
            try:
                text, confidence = await self._call_groq(system_prompt, conversation_history, customer_message)
            except Exception:
                logger.exception("Groq API call failed; falling back to mock response")
                return self._mock_response(customer_message, turn_count, language)
        else:
            return self._mock_response(customer_message, turn_count, language)

        # 4. Check turn limit
        if turn_count >= max_turns:
            return AIResponse(
                text=text,
                confidence=min(confidence, 0.3),
                should_escalate=True,
                escalation_reason="max_turns_exceeded",
            )

        # 5. Determine escalation based on confidence threshold
        should_escalate = confidence < confidence_threshold
        escalation_reason = f"low_confidence ({confidence:.2f})" if should_escalate else None

        return AIResponse(
            text=text,
            confidence=confidence,
            should_escalate=should_escalate,
            escalation_reason=escalation_reason,
        )

    # ------------------------------------------------------------------
    # Groq integration
    # ------------------------------------------------------------------

    async def _call_groq(
        self,
        system_prompt: str,
        history: list[dict],
        message: str,
    ) -> tuple[str, float]:
        """Call the Groq chat completion API and return the response text."""
        client = AsyncGroq(api_key=self.groq_api_key)

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        completion = await client.chat.completions.create(
            model=self.default_model,
            messages=messages,
            temperature=0.7,
            max_tokens=300,
        )

        text = (completion.choices[0].message.content or "").strip()
        return text, 0.85

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
