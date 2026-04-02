# Angel Tel — Production Voice Flow Specification
## Based on How Retell, Vapi, LiveKit, Pipecat, and Custom Prod Systems Actually Work

---

## 1. Reality Check: What Your Spec Had vs What Production Systems Use

Your original spec had the right instincts but several approaches that differ from how production systems handle things. Here's the honest comparison:

### What You Got Right
- Streaming STT → LLM → TTS pipeline (this is the universal architecture)
- Sentence-level TTS chunking (every production system does this)
- Echo guard concept (critical, everyone needs this)
- Supervisor listen/whisper/barge (standard contact center features)

### What Production Systems Do Differently

| Your Approach | What Prod Systems Actually Use | Why |
|---|---|---|
| Custom energy-based VAD (`calculate_energy_dbfs`) | **Silero VAD** — a 2MB ONNX neural model processing 30ms chunks in <1ms | Energy thresholds are unreliable. They break on background noise, music-on-hold bleed, HVAC hum. Silero is trained on 6000+ languages and handles noise natively. Every serious framework (Pipecat, LiveKit, Retell) uses Silero VAD. |
| Custom echo suppression via `playback_active` flag + energy thresholds | **WebRTC's built-in AEC** (Acoustic Echo Cancellation) + a lightweight server-side echo gate | Browser/WebRTC handles AEC in hardware. For telephony (Twilio/Plivo media streams), prod systems use the transport layer's echo cancellation, not hand-rolled energy comparison. Your approach creates a maintenance nightmare of threshold tuning per device. |
| Raw energy-based barge-in detection | **VAD-based barge-in with interruption strategies** (min-word count, sustained speech duration) | Pipecat literally ships `MinWordsInterruptionStrategy` — require N transcribed words before triggering barge-in. This eliminates false positives from coughs, "uh-huh", and background noise far better than energy thresholds. |
| Custom endpointing via silence duration + `is_final` | **Smart Turn Detection** — VAD + STT finality + LLM-based turn prediction | LiveKit ships a dedicated turn detector model alongside Silero VAD. Pipecat uses `stop_secs` parameter tuning on VAD. Fixed silence thresholds (your 700ms) either cut off slow speakers or add unnecessary latency for fast speakers. |
| Sarvam for all Indian language STT/TTS | Sarvam is fine for Indian languages, but **Deepgram Nova-3** or **AssemblyAI Universal-Streaming** for English STT, **Cartesia/ElevenLabs/Rime** for TTS | Production systems use the best model per task. Sarvam is good for Marathi/Hindi but not competitive for English STT accuracy or TTS naturalness. Mix providers. |
| Groq Llama 3.3 70B | Groq is a great choice for TTFT (time-to-first-token). Production systems commonly use **GPT-4o** or **Gemini 2.5 Flash** for reliability, with Groq as a fast alternative | Daily.co's official advice: "Don't start with anything other than GPT-4o or Gemini 2.5 Flash" for voice. Groq's Llama is fast but instruction-following and tool-calling lag behind. |
| Estimating playback duration from audio bytes | **TTS word-level timestamps** for exact playback tracking | Cartesia, ElevenLabs, and Rime all provide word-level timestamps. This tells you exactly which word the caller heard when they interrupted — critical for maintaining conversation context. Without it, you're guessing. |

---

## 2. The Production Voice Pipeline (How It Actually Works)

Every production voice platform — Retell, Vapi, Bland, and custom builds on Pipecat/LiveKit — uses the same fundamental architecture, called the **Cascaded Streaming Pipeline**:

```
┌─────────────────────────────────────────────────────────────┐
│                    TRANSPORT LAYER                           │
│  SIP Trunk (Twilio/Plivo) ──► WebRTC Room (LiveKit/Daily)   │
│  OR: Twilio Media Streams (WebSocket, raw μ-law audio)      │
│                                                             │
│  This layer handles:                                        │
│   • Codec negotiation (μ-law ↔ PCM ↔ Opus)                 │
│   • Jitter buffering                                        │
│   • Echo cancellation (AEC) at the transport level          │
│   • Audio resampling (8kHz telephony ↔ 16kHz for models)    │
└───────────────────────┬─────────────────────────────────────┘
                        │ PCM audio frames (16kHz, 16-bit)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                      VAD LAYER                              │
│  Silero VAD (ONNX, <1ms per 30ms chunk)                     │
│                                                             │
│  Outputs events:                                            │
│   • UserStartedSpeaking                                     │
│   • UserStoppedSpeaking (after configurable silence)        │
│                                                             │
│  Config:                                                    │
│   • threshold: 0.5 (speech confidence, 0-1)                 │
│   • min_speech_duration: 250ms                              │
│   • min_silence_duration: 300ms (for endpointing)           │
│   • speech_pad: 30ms (prepend to avoid cutting phonemes)    │
└───────────────────────┬─────────────────────────────────────┘
                        │ speech segments only
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                      STT LAYER                              │
│  Streaming STT (Deepgram Nova-3 / Sarvam for Indian langs)  │
│                                                             │
│  Receives: audio chunks during VAD speech segments          │
│  Outputs:  interim transcripts (real-time) + final transcript│
│                                                             │
│  Key: utterance_end_ms tuning per use case                  │
│   • Receptionist/support: 800-1000ms (let people finish)    │
│   • Booking confirmation: 400-600ms (quick exchanges)       │
│   • IVR-style: 300ms (short answers expected)               │
└───────────────────────┬─────────────────────────────────────┘
                        │ final transcript text
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                      LLM LAYER                              │
│  Streaming LLM (GPT-4o / Gemini 2.5 Flash / Groq Llama)    │
│                                                             │
│  Input: conversation history + system prompt + tools        │
│  Output: streaming token response                           │
│                                                             │
│  Critical metric: TTFT (Time to First Token)                │
│   • Groq: ~200-350ms                                        │
│   • GPT-4o: ~300-500ms                                      │
│   • Gemini 2.5 Flash: ~250-400ms                            │
│                                                             │
│  Sentence aggregation: buffer tokens until sentence boundary│
│  Then fire that sentence to TTS immediately                 │
└───────────────────────┬─────────────────────────────────────┘
                        │ sentence-level text chunks
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                      TTS LAYER                              │
│  Streaming TTS (Cartesia / ElevenLabs / Rime / Sarvam)      │
│                                                             │
│  Input: sentence text                                       │
│  Output: audio chunks + word-level timestamps               │
│                                                             │
│  Word timestamps enable:                                    │
│   • Knowing exactly what the user heard on barge-in         │
│   • Accurate transcript reconstruction                      │
│   • Precise playback position tracking                      │
│                                                             │
│  Latency targets:                                           │
│   • Cartesia Sonic: <100ms to first audio                   │
│   • ElevenLabs: ~150ms to first audio                       │
│   • Sarvam (Indian langs): ~200-300ms to first audio        │
└───────────────────────┬─────────────────────────────────────┘
                        │ audio frames + timestamps
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                   PLAYBACK LAYER                            │
│  Audio output queue → Transport → Caller's phone            │
│                                                             │
│  Features:                                                  │
│   • FIFO queue for gapless playback                         │
│   • Cancel-safe (flush on barge-in)                         │
│   • Playback position tracked via word timestamps           │
│   • Sets agent_speaking flag for echo gate                  │
└─────────────────────────────────────────────────────────────┘
```

### Total Latency Budget (Production Target)

```
End of user speech → First AI audio heard by caller

Endpointing (VAD silence):      300-500ms  (tunable)
STT finalization:                 50-150ms
Network to LLM:                   20-50ms
LLM TTFT:                       200-400ms
Sentence buffer:                  50-100ms  (wait for first sentence end)
TTS first audio:                 100-200ms
Network back to caller:           20-50ms
─────────────────────────────────────────
Total target:                   ~500-800ms  (p50)
Acceptable ceiling:              ~1500ms    (p95)
```

---

## 3. Barge-In: How Production Systems Actually Handle It

### The Pipecat/LiveKit Approach (Industry Standard)

Production systems do NOT use raw energy thresholds. They use a multi-layer detection system:

```
Caller audio arrives WHILE agent is speaking
                │
                ▼
        ┌───────────────┐
        │   Silero VAD  │──── Is this speech? (neural model, not energy)
        └───────┬───────┘
                │ YES, speech detected
                ▼
        ┌───────────────────────┐
        │  Interruption Strategy │
        │                       │
        │  Options (pick one):  │
        │                       │
        │  A) MinWordsStrategy  │──── Wait for N transcribed words (e.g. 3)
        │     (Pipecat default) │     before confirming barge-in.
        │                       │     "Uh-huh" = 1 word = ignored.
        │                       │     "Actually wait I need" = 4 words = barge-in.
        │                       │
        │  B) DurationStrategy  │──── Speech sustained > Xms (e.g. 500ms)
        │                       │
        │  C) LLM-Aware         │──── Feed transcript to small classifier:
        │     (advanced)        │     "Is this a backchannel or a real interruption?"
        │                       │     Catches: "mm-hmm", "yeah", "okay"
        └───────────┬───────────┘
                    │ CONFIRMED BARGE-IN
                    ▼
        ┌───────────────────────┐
        │  Interruption Frame   │ ← Pipecat: StartInterruptionFrame
        │  (HIGH PRIORITY)      │   LiveKit: agent automatically handles
        │                       │
        │  This frame BYPASSES  │
        │  the normal queue and │
        │  is processed         │
        │  immediately by ALL   │
        │  processors           │
        └───────────┬───────────┘
                    │
        ┌───────────▼───────────┐
        │  Pipeline Cancellation │
        │                       │
        │  1. LLM: cancel       │ ← Abort streaming completion
        │     in-flight request │
        │                       │
        │  2. TTS: cancel       │ ← Stop synthesizing
        │     pending synthesis │
        │                       │
        │  3. Audio queue:      │ ← Flush all queued chunks
        │     flush/clear       │
        │                       │
        │  4. Transport: stop   │ ← Stop sending audio to caller
        │     audio output      │
        │                       │
        │  5. Context: truncate │ ← Use word-level timestamps to record
        │     assistant message │   exactly what the caller heard
        │     to what was heard │   before the interruption
        └───────────┬───────────┘
                    │
                    ▼
          Back to LISTENING state
          (new user speech is being captured)
```

### The Word-Level Timestamp Insight

This is the thing most custom implementations miss. When the caller interrupts, you need to know what they actually heard. Without word-level timestamps from TTS, you're guessing.

```
AI intended to say: "I can help you with your billing. Let me check your account details."

AI actually got through: "I can help you with your bill—" [BARGE-IN]

With word timestamps from Cartesia/ElevenLabs:
  "I"      → 0ms
  "can"    → 120ms
  "help"   → 240ms
  "you"    → 350ms
  "with"   → 430ms
  "your"   → 520ms
  "bill—"  → 610ms  ← barge-in happened here

Conversation context saved:
  assistant: "I can help you with your bill"  (truncated to heard portion)
  user: "No, it's not about billing, it's about..."
```

Without this, your LLM thinks it said the full sentence and the conversation history is wrong.

### Critical Pipecat Config for Barge-In

```python
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.audio.interruptions.min_words_interruption_strategy import (
    MinWordsInterruptionStrategy
)

task = PipelineTask(
    pipeline,
    params=PipelineParams(
        allow_interruptions=True,
        interruption_strategies=[
            MinWordsInterruptionStrategy(min_words=3)
        ]
    )
)
```

---

## 4. Echo Cancellation: The Real Approach

### What Production Systems Do

There are TWO layers of echo cancellation, and you only need to build one of them:

**Layer 1: Transport-Level AEC (you get this for free)**
- WebRTC: Built-in `echoCancellation: true` in `getUserMedia` — handles acoustic echo at the browser/OS level
- Twilio Media Streams: Twilio's infrastructure handles echo cancellation before audio reaches your WebSocket
- Plivo: Similar — provider-level AEC

**Layer 2: Server-Side Echo Gate (you build this, but it's simple)**

```python
# This is what production systems actually use — not energy comparison
class EchoGate:
    """Simple server-side echo gate. Attenuates mic input while agent speaks."""

    def __init__(self):
        self.agent_speaking = False

    def on_agent_start_speaking(self):
        self.agent_speaking = True

    def on_agent_stop_speaking(self):
        # Small delay to account for audio pipeline latency
        asyncio.get_event_loop().call_later(0.15, self._clear_speaking)

    def _clear_speaking(self):
        self.agent_speaking = False

    def should_process_audio(self, frame: bytes) -> bool:
        """During agent speech, only pass through if VAD detects LOUD speech
        (likely real human, not echo)."""
        if not self.agent_speaking:
            return True  # Agent not speaking, process everything

        # Delegate to Silero VAD — it handles this better than energy thresholds
        # If VAD says speech with high confidence during agent output,
        # it's probably a real barge-in
        return False  # Default: suppress during agent speech
```

### Why Your Approach Was Over-Engineered

Your spec defined separate `ECHO_ENERGY_THRESHOLD` (-35 dBFS) and `BARGE_IN_ENERGY_THRESHOLD` (-20 dBFS) with manual tuning. The problem:

- These thresholds change with every phone model, carrier, and network condition
- Speakerphone vs earpiece completely changes the energy dynamics
- Background noise (car, cafe, street) shifts the baseline
- You end up tuning per-deployment, which doesn't scale

Production systems let Silero VAD (a neural model trained on noisy, real-world audio) make the speech/non-speech decision, and combine it with transport-level AEC. This is more robust and requires zero per-deployment tuning.

---

## 5. Turn Detection (Endpointing): The Hardest Problem

This is where production teams spend the most time tuning. The question: "Has the user finished their turn, or are they just pausing?"

### The Spectrum of Approaches

**Level 1: Fixed Silence Timeout (What You Had)**
```
User stops speaking → wait 700ms of silence → finalize
```
Problems: Cuts off slow speakers. Adds unnecessary delay for fast speakers. Doesn't understand conversational context.

**Level 2: VAD + STT Hybrid (Most Production Systems)**
```
Silero VAD detects silence → wait stop_secs (300-500ms)
    → check if STT has returned is_final=true
    → if yes: finalize turn
    → if no: wait a bit more for STT to catch up
```
This is what Pipecat does with `SileroVADAnalyzer(params=VADParams(stop_secs=0.3))`.

**Level 3: Smart Turn Detection (LiveKit, Advanced)**
```
VAD silence + STT final + small LLM classifier:
    "Given the transcript so far, has the user finished their thought?"

Input: "I need to change my flight from Mumbai to—"
Classifier: NOT DONE (incomplete sentence, trailing preposition)
→ Keep waiting

Input: "I need to change my flight from Mumbai to Delhi."
Classifier: DONE (complete sentence)
→ Finalize immediately (don't wait for full silence timeout)
```

LiveKit ships a dedicated turn detector model for this. It runs alongside Silero VAD and dramatically reduces both false-early and false-late turn endings.

### Recommended Configuration for Angel Tel

```python
# For your bilingual (English + Marathi) contact center use case:

vad_config = {
    "model": "silero_vad_v5",
    "threshold": 0.5,           # Speech confidence
    "min_speech_duration_ms": 250,  # Ignore sub-250ms sounds
    "min_silence_duration_ms": 300, # Base silence for endpointing
    "speech_pad_ms": 30,        # Don't cut off first phoneme
}

# Per-scenario tuning:
endpointing_profiles = {
    "ivr_digit_collection": {
        "stop_secs": 0.3,    # Quick — expecting short answers
        "stt_utterance_end_ms": 300,
    },
    "ai_conversation": {
        "stop_secs": 0.5,    # Medium — natural conversation
        "stt_utterance_end_ms": 700,
    },
    "complaint_handling": {
        "stop_secs": 0.8,    # Long — let people vent
        "stt_utterance_end_ms": 1000,
    },
}
```

---

## 6. The Provider Stack: What to Use Where

Based on what production systems actually deploy:

### STT (Speech-to-Text)

| Provider | Best For | Latency | Cost | Notes |
|---|---|---|---|---|
| **Deepgram Nova-3** | English, general accuracy | ~300ms streaming | ~$0.006/min | Most widely used in prod voice AI. Streaming with good endpointing. |
| **AssemblyAI Universal-Streaming** | English, complex audio | ~300ms immutable transcripts | $0.15/hr (~$0.0025/min) | Great for noisy environments. |
| **Sarvam** | Marathi, Hindi, Indian English | ~300-500ms | Varies | Good for your Indian language use case. Keep this. |
| **Twilio STT** | Basic English, built-in to Twilio | ~500ms | Bundled with Twilio | Mediocre accuracy, but zero integration effort. |

**Recommendation**: Deepgram Nova-3 for English, Sarvam for Marathi/Hindi. Don't use a single provider for both.

### LLM (Language Model)

| Provider | TTFT (p50) | Quality | Cost | Notes |
|---|---|---|---|---|
| **GPT-4o** | ~300-500ms | Best instruction following | ~$0.002/min voice | Gold standard. Start here. |
| **Gemini 2.5 Flash** | ~250-400ms | Very good, fast | Competitive | Strong alternative to GPT-4o. |
| **Groq (Llama 3.3 70B)** | ~200-350ms | Good | ~$0.002/min | Fastest TTFT. Weaker on complex tool calling. |
| **Cerebras** | ~200ms | Good | Competitive | Fastest raw speed, but US-only regions. Latency from India would eat the advantage. |

**Recommendation**: GPT-4o as primary, Groq as fallback/fast path. Groq's advantage only matters if your server is US-based and close to their infra.

### TTS (Text-to-Speech)

| Provider | Time to First Audio | Quality | Word Timestamps | Notes |
|---|---|---|---|---|
| **Cartesia Sonic** | <100ms | Excellent | ✅ Yes | Fastest. Best for low-latency. |
| **ElevenLabs** | ~150ms | Best naturalness | ✅ Yes | Most natural voices. Higher cost. |
| **Rime** | ~120ms | Good | ✅ Yes | Good balance of speed and quality. |
| **Sarvam** | ~200-300ms | Good for Indian | ❌ No timestamps | Keep for Marathi/Hindi. But no word timestamps means weaker barge-in context. |

**Recommendation**: Cartesia for English (speed + timestamps), Sarvam for Marathi/Hindi (language coverage). Accept that Marathi barge-in context will be less precise without word timestamps.

### VAD (Voice Activity Detection)

| Tool | Notes |
|---|---|
| **Silero VAD v5** | Industry standard. Used by Pipecat, LiveKit, and essentially every production voice agent. 2MB ONNX model, <1ms per 30ms chunk, works at 8kHz and 16kHz. No alternatives worth considering. |

---

## 7. Framework Decision: Build vs Buy for Angel Tel

Your current approach is a full custom build. Here's how it compares:

### Option A: Stay Custom (Current Approach)
- **Pros**: Full control, no per-minute platform markup, custom handoff logic
- **Cons**: You're rebuilding what Pipecat/LiveKit already solved (VAD, turn detection, interruption handling, audio resampling, buffer management)
- **Cost**: Engineering time to handle edge cases that frameworks have already fixed

### Option B: Use Pipecat as Voice Engine (Recommended)
- **Pros**: Battle-tested interruption handling, 68+ service integrations, automatic pipeline cancellation on barge-in, Silero VAD built in, works with your existing FastAPI backend
- **Cons**: Framework opinions may conflict with your state machine design
- **How it fits**: Pipecat handles the real-time voice pipeline. Your `HandoffEngine` and state machine sit above it, controlling when to transition between IVR → AI → Human.

```python
# How Pipecat would fit into your architecture:

# Your existing HandoffEngine stays as-is
# Pipecat replaces VoiceAISession internals

from pipecat.pipeline import Pipeline
from pipecat.services.deepgram import DeepgramSTT
from pipecat.services.cartesia import CartesiaTTS
from pipecat.services.openai import OpenAILLM
from pipecat.transports.services.daily import DailyTransport
from pipecat.audio.vad.silero import SileroVADAnalyzer

pipeline = Pipeline([
    transport.input(),       # Audio from caller
    stt,                     # Deepgram / Sarvam
    context_aggregator.user(),
    llm,                     # GPT-4o / Groq
    tts,                     # Cartesia / Sarvam
    transport.output(),      # Audio to caller
    context_aggregator.assistant(),
])

task = PipelineTask(pipeline, params=PipelineParams(
    allow_interruptions=True,
    interruption_strategies=[MinWordsInterruptionStrategy(min_words=3)]
))

# Your handoff logic hooks into Pipecat events:
@transport.event_handler("on_participant_left")
async def on_caller_hangup(transport, participant):
    await handoff_engine.transition(conv_id, trigger="CALLER_HANGUP")

# Escalation triggered by AI response analysis:
@llm.event_handler("on_completion")  
async def check_escalation(llm, response_text):
    if should_escalate(response_text, tenant_config):
        await handoff_engine.transition(conv_id, trigger="AI_ESCALATE")
        task.cancel()  # Stop the voice pipeline
```

### Option C: Use LiveKit (If You Need WebRTC + Telephony)
- Better than Pipecat if you need browser-based softphone + phone calls in the same system (you do — your dashboard has a Plivo Browser SDK softphone)
- LiveKit handles WebRTC rooms natively, SIP trunking, and voice AI pipeline

---

## 8. Revised Flow for Angel Tel

Based on production patterns, here's the recommended flow:

### Phase 1: Call Setup (Same as Your Current)
```
Inbound → Twilio/Plivo webhook → Create Conversation → IVR greeting → DTMF
```
No changes needed. Your IVR engine is fine.

### Phase 2: AI Voice Session (Revised)

```
IVR completes → Start Pipecat/custom pipeline

Pipeline components:
  Transport: Twilio Media Stream (WebSocket) or Plivo Audio Stream
  VAD:       Silero VAD (stop_secs=0.5 for conversation)
  STT:       Deepgram Nova-3 (English) / Sarvam (Marathi)
  LLM:       GPT-4o with streaming (system prompt includes language + persona)
  TTS:       Cartesia (English) / Sarvam (Marathi)
  
Barge-in:   MinWordsStrategy(min_words=3)
Turn detect: VAD silence (500ms) + STT is_final
Echo:        Transport-level AEC + server-side echo gate (not energy thresholds)
```

### Phase 3: Escalation Decision

```python
# After each AI turn, evaluate escalation:

async def evaluate_escalation(ai_response: str, conversation: Conversation):
    # 1. Keyword detection (language-aware)
    if contains_escalation_keyword(ai_response, conversation.language):
        return EscalationReason.KEYWORD
    
    # 2. Confidence scoring (from LLM structured output)
    confidence = extract_confidence(ai_response)
    if confidence < tenant.ai_threshold:
        return EscalationReason.LOW_CONFIDENCE
    
    # 3. Turn count limit
    if conversation.ai_turn_count > tenant.max_ai_turns:
        return EscalationReason.MAX_TURNS
    
    # 4. Sentiment detection (optional, from LLM)
    if detect_frustration(ai_response):
        return EscalationReason.NEGATIVE_SENTIMENT
    
    return None  # Continue AI handling
```

### Phase 4: Handoff to Human (Revised)

```
AI decides to escalate
    │
    ├─ AI says: "Let me connect you with an agent" (TTS plays)
    ├─ Wait for TTS to finish (using word timestamps for exact timing)
    ├─ Kill voice pipeline (cancel all tasks)
    ├─ Transition → QUEUED_FOR_HUMAN
    ├─ routing_engine.find_agent(skills, language, tenant)
    │
    ├─ IF agent available:
    │   ├─ Bridge call (Twilio conference / Plivo multiparty)
    │   ├─ Send handoff context to agent dashboard:
    │   │   • Conversation summary (from LLM)
    │   │   • Key entities extracted (name, account, issue)
    │   │   • Escalation reason
    │   │   • Full transcript
    │   ├─ Transition → HUMAN_HANDLING
    │   └─ Emit handoff.ai_to_human event
    │
    └─ IF no agent available:
        ├─ Play hold music
        ├─ Announce queue position every 30s
        ├─ Offer callback option after 2 min
        └─ Retry agent routing on agent_status_change events
```

---

## 9. What to Change in Your Codebase

Priority-ordered changes based on production best practices:

### P0: Replace Energy-Based VAD with Silero VAD
```bash
pip install silero-vad
```
This single change eliminates your custom `calculate_energy_dbfs`, `ECHO_ENERGY_THRESHOLD`, `BARGE_IN_ENERGY_THRESHOLD`, and `MIN_SPEECH_FRAMES` — all replaced by a neural model that just works.

### P0: Add Word-Level TTS Timestamps
Switch English TTS to Cartesia or ElevenLabs. Use word timestamps to track playback position and truncate assistant context on barge-in.

### P1: Replace Custom Barge-In with Strategy Pattern
Implement `MinWordsInterruptionStrategy` (or use Pipecat's). Require 2-3 transcribed words before confirming barge-in. This eliminates false positives from coughs, "mm-hmm", and background noise.

### P1: Split STT Providers by Language
Deepgram Nova-3 for English, Sarvam for Marathi/Hindi. Don't use a single STT for both.

### P2: Consider LLM Upgrade
Test GPT-4o or Gemini 2.5 Flash alongside Groq for instruction following quality. Keep Groq as a fallback for when speed matters most.

### P2: Adopt Pipecat or LiveKit for Voice Pipeline
Instead of maintaining your own `VoiceAISession`, use a framework that handles the hard parts (resampling, buffer management, interruption propagation, provider failover). Your `HandoffEngine` and state machine are your competitive advantage — the audio pipeline is not.

### P3: Add Automatic Service Failover
Pipecat recently added `ServiceSwitcherStrategyFailover` — when STT/TTS/LLM fails, automatically rotate to backup providers. Your custom build needs this for production resilience.

---

## 10. Key Metrics to Track (From Hamming's 4M+ Call Analysis)

| Metric | Target (p50) | Target (p95) | How to Measure |
|---|---|---|---|
| Voice-to-voice latency | <800ms | <1500ms | End of user speech → first AI audio |
| Barge-in detection latency | <200ms | <500ms | User speech onset → TTS stopped |
| Agent stop latency | <300ms | <500ms | Barge-in detected → silence on caller's end |
| False positive interruptions | <5% of turns | — | Barge-ins where user was just saying "uh-huh" |
| STT accuracy (WER) | <10% | — | Word error rate on your actual call audio |
| Escalation accuracy | >90% | — | Correct escalation decisions vs total |
| Call completion rate | >95% | — | Calls that don't drop due to technical errors |