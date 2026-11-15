// Public, browser-safe settings only. Never put private keys here.
// Leave the Supabase/Vapi values empty to run in demo mode with sample data.
const PROD = 'https://vaani-divyasree.vercel.app';
const onLocalhost = ['localhost', '127.0.0.1'].includes(location.hostname);

export const config = {
  appName: 'Whispers of the Wind (WOW)',
  vapiPublicKey: '57c1aac2-85a5-4050-9dd5-cd0da4a2eaa5',      // locked to this site + Divya
  vapiAssistantId: 'cd8fc3ff-c406-4352-a9bf-b2f4a956d54d',    // written by scripts/sync_assistant.py
  supabaseUrl: 'https://uykwlbmrrapxsbokwlsu.supabase.co',
  supabaseAnonKey: 'sb_publishable_8JIappU7mfBneWO4MFe4fQ_XDzNG0_L', // publishable key: safe in the browser (RLS + masked views)
  // Python backend (FastAPI). Same site on Vercel; the local dashboard talks to the deployed API.
  apiBaseUrl: onLocalhost ? `${PROD}/api` : '/api',
};

export const isLive = {
  vapi: () => !!(config.vapiPublicKey && config.vapiAssistantId),
  supabase: () => !!(config.supabaseUrl && config.supabaseAnonKey),
  api: () => !!config.apiBaseUrl,
};

// Asks the backend whether a real phone line is connected (Twilio bridge or Vapi number).
let phoneInfo;
export async function phoneCalling() {
  phoneInfo ??= fetch(`${config.apiBaseUrl}/config`).then(r => r.json()).catch(() => ({ phoneCalling: false }));
  return (await phoneInfo).phoneCalling === true;
}
