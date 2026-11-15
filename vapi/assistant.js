// The full Vapi assistant configuration for Aanya, kept in code so it is versioned and repeatable.

// What the AI extracts from every call (Vapi "Structured Output", replaces the old analysisPlan).
export const leadAnalysisOutput = {
  name: 'Lead Qualification',
  type: 'ai',
  description: 'Qualification result for a Divyasree Whispers of the Wind outbound call',
  schema: {
    type: 'object',
    properties: {
      summary: { type: 'string', description: '2-3 sentence summary: who the lead is, what they said on each checkpoint, objections, and the agreed next step.' },
      interest: { type: 'string', enum: ['hot', 'warm', 'cold'], description: 'hot = budget clearly fits (₹92.4 lakh+), location and timeline are OK, AND an expert callback is booked. warm = interested or callback booked, but budget is a stretch/unclear or another checkpoint is unresolved. cold = not interested, clearly not a fit, or asked not to be called.' },
      intent: { type: 'string', description: 'Self-use, Investment, Both, or Unknown, with a few words of detail.' },
      geography_fit: { type: 'string', description: 'Yes / No / Hesitant, plus a short reason.' },
      budget_fit: { type: 'string', description: 'Yes / No / Stretch, plus the budget mentioned if any.' },
      timeline_fit: { type: 'string', description: 'Yes / No / Unsure regarding December 2029 phased possession.' },
      sentiment_start: { type: 'string', enum: ['positive', 'calm', 'hesitant', 'irritated', 'angry'] },
      sentiment_end: { type: 'string', enum: ['positive', 'calm', 'hesitant', 'irritated', 'angry'] },
      language: { type: 'string', enum: ['English', 'Hindi', 'Hinglish', 'Other'] },
      callback_time: { type: 'string', description: 'Agreed day/time for the Property Expert call, or empty if none.' },
      do_not_call: { type: 'boolean', description: 'True if the lead asked not to be contacted again.' },
    },
    required: ['summary', 'interest', 'sentiment_end', 'do_not_call'],
  },
};

import { voiceConfig } from '../web/js/campaign-data.js';

// Live-call brain. Default: OpenAI GPT-4.1-mini billed to Vapi's free credits (fast, good Hindi,
// automatic prompt caching, no per-minute cap). Override with VAPI_LLM=provider:model in .env,
// e.g. VAPI_LLM=groq:openai/gpt-oss-20b (note: Groq's free tier allows only 8k tokens/minute).
export function parseLlm(spec = 'openai:gpt-4.1-mini') {
  const i = spec.indexOf(':');
  return { provider: spec.slice(0, i), model: spec.slice(i + 1) };
}

export function buildAssistant({ systemPrompt, voiceId, serverUrl, structuredOutputId, llm = parseLlm() }) {
  return {
    name: 'Aanya · Divyasree WOW',
    firstMessageMode: 'assistant-speaks-first',
    firstMessage: "Hello {{ name | default: 'there' }}! This is Aanya, a consultant from Divyasree Developers, calling about Whispers of the Wind, our villa plot community near Nandi Hills in North Bengaluru. Is this a good time for two minutes?",

    // Brain: low temperature to stay factual.
    model: {
      provider: llm.provider,
      model: llm.model,
      temperature: 0.3,
      maxTokens: llm.provider === 'groq' ? 600 : 160,   // gpt-oss models spend tokens on reasoning first
      messages: [{ role: 'system', content: systemPrompt }],
      tools: [{ type: 'endCall' }],
    },

    // Ears: Deepgram nova-3 in multilingual mode (English + Hindi code-switching).
    transcriber: { provider: 'deepgram', model: 'nova-3', language: 'multi' },

    // Voice: ElevenLabs Flash v2.5 (lowest latency, speaks Hindi too).
    voice: voiceConfig(voiceId),

    // Turn-taking: don't cut the user off; stop instantly when they interrupt.
    startSpeakingPlan: { waitSeconds: 0.4, smartEndpointingPlan: { provider: 'livekit' } },
    stopSpeakingPlan: { numWords: 1, voiceSeconds: 0.2, backoffSeconds: 1 },
    backgroundSpeechDenoisingPlan: { smartDenoisingPlan: { enabled: true } },

    silenceTimeoutSeconds: 15,     // hang up after 15 s of silence (protects free credits)
    maxDurationSeconds: 240,       // hard cap: 4 minutes per call
    endCallMessage: 'Thank you for your time. Have a lovely day!',
    voicemailMessage: 'Hello, this is Aanya from Divyasree Developers about Whispers of the Wind, our villa plots near Nandi Hills. I will try you again later. Thank you!',

    // Recording + transcript + AI analysis after every call.
    artifactPlan: {
      recordingEnabled: true,
      recordingFormat: 'mp3',          // ~8x smaller than WAV: faster to copy, cheaper to store
      ...(structuredOutputId ? { structuredOutputIds: [structuredOutputId] } : {}),
    },

    // Send the end-of-call report to n8n.
    ...(serverUrl ? { server: { url: serverUrl }, serverMessages: ['end-of-call-report', 'status-update'] } : {}),

    metadata: { campaign_id: 'divyasree-wow', app: 'vaani' },
  };
}
