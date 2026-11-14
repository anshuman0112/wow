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
      interest: { type: 'string', enum: ['hot', 'warm', 'cold'], description: 'hot = qualified and booked/eager for expert call; warm = interested but one checkpoint unresolved; cold = not interested, not a fit, or asked not to be called.' },
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

// Text replacements applied right before speech so the voice pronounces names correctly.
const pronunciationReplacements = [
  ['Divyasree', 'Divya-shree'], ['DivyaSree', 'Divya-shree'],
  ['Nandi', 'Nundhi'], ['Devanahalli', 'Dayva-nahalli'],
  ['Doddaballapura', 'Dodda-balla-pura'], ['lakh', 'laakh'], ['Lakh', 'Laakh'],
].map(([key, value]) => ({ type: 'exact', key, value }));

export function buildAssistant({ systemPrompt, voiceId, serverUrl, structuredOutputId }) {
  return {
    name: 'Aanya · Divyasree WOW',
    firstMessageMode: 'assistant-speaks-first',
    firstMessage: "Hello {{ name | default: 'there' }}! This is Aanya, a consultant from Divyasree Developers, calling about Whispers of the Wind, our villa plot community near Nandi Hills in North Bengaluru. Is this a good time for two minutes?",

    // Brain: Groq (free tier), fast and low-temperature to stay factual.
    model: {
      provider: 'groq',
      model: 'llama-3.3-70b-versatile',
      temperature: 0.3,
      maxTokens: 160,
      messages: [{ role: 'system', content: systemPrompt }],
      tools: [{ type: 'endCall' }],
    },

    // Ears: Deepgram nova-3 in multilingual mode (English + Hindi code-switching).
    transcriber: { provider: 'deepgram', model: 'nova-3', language: 'multi' },

    // Voice: ElevenLabs Flash v2.5 (lowest latency, speaks Hindi too).
    voice: {
      provider: '11labs',
      voiceId,
      model: 'eleven_flash_v2_5',
      stability: 0.5,
      similarityBoost: 0.75,
      chunkPlan: { enabled: true, formatPlan: { enabled: true, replacements: pronunciationReplacements } },
    },

    // Turn-taking: don't cut the user off; stop instantly when they interrupt.
    startSpeakingPlan: { waitSeconds: 0.4, smartEndpointingPlan: { provider: 'livekit' } },
    stopSpeakingPlan: { numWords: 1, voiceSeconds: 0.2, backoffSeconds: 1 },
    backgroundSpeechDenoisingPlan: { smartDenoisingPlan: { enabled: true } },

    silenceTimeoutSeconds: 20,
    maxDurationSeconds: 300,
    endCallMessage: 'Thank you for your time. Have a lovely day!',
    voicemailMessage: 'Hello, this is Aanya from Divyasree Developers about Whispers of the Wind, our villa plots near Nandi Hills. I will try you again later. Thank you!',

    // Recording + transcript + AI analysis after every call.
    artifactPlan: {
      recordingEnabled: true,
      ...(structuredOutputId ? { structuredOutputIds: [structuredOutputId] } : {}),
    },

    // Send the end-of-call report to n8n.
    ...(serverUrl ? { server: { url: serverUrl }, serverMessages: ['end-of-call-report', 'status-update'] } : {}),

    metadata: { campaign_id: 'divyasree-wow', app: 'vaani' },
  };
}
