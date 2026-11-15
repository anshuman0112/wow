// Campaign #1 — everything the agent knows and follows.
// The data lives in campaign.json so the Python backend and this dashboard share ONE source of truth.
// Source of truth for content: the Revspot assignment PDF. Web extras are tagged and never override the PDF.
import data from './campaign.json' with { type: 'json' };
import { libraryVoices } from './voices.generated.js';

export const { campaign, pinnedVoices, flow, facts, pronunciation, edgeCases } = data;

// Pinned voices + everything in your ElevenLabs library (from `npm run voices`), no duplicates.
export const voices = (() => {
  const lib = new Map(libraryVoices.map(v => [v.id, v]));
  const pinned = pinnedVoices.map(p => ({ ...lib.get(p.id), ...p, pinned: true, previewUrl: lib.get(p.id)?.previewUrl || '' }));
  const rest = libraryVoices.filter(v => !pinnedVoices.some(p => p.id === v.id)).map(v => ({
    id: v.id, name: v.name, previewUrl: v.previewUrl, category: v.category, freePlanApi: v.freePlanApi,
    style: [v.gender, v.accent, v.description].filter(Boolean).join(' · ') || v.category,
    languages: v.language || 'EN (multilingual model)',
  }));
  return [...pinned, ...rest];
})();

// Voice settings shared with the Python backend (backend/vapi_assistant.py builds the same object).
export function voiceConfig(voiceId = voices[0].id) {
  return {
    ...data.voiceSettings,
    voiceId,
    chunkPlan: { enabled: true, formatPlan: { enabled: true, replacements: data.sayAs.map(([key, value]) => ({ type: 'exact', key, value })) } },
  };
}
