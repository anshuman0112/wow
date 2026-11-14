// Public, browser-safe settings only. Never put private keys here.
// Leave empty to run in demo mode with sample data.
export const config = {
  appName: 'Vaani',
  vapiPublicKey: '',      // Vapi dashboard → API Keys → Public key
  vapiAssistantId: '',    // created by scripts/sync_assistant.js
  supabaseUrl: '',        // https://xxxx.supabase.co
  supabaseAnonKey: '',    // anon key (read access protected by RLS)
  n8nBaseUrl: '',         // e.g. https://xxxx.ngrok-free.app/webhook
};

export const isLive = {
  vapi: () => !!(config.vapiPublicKey && config.vapiAssistantId),
  supabase: () => !!(config.supabaseUrl && config.supabaseAnonKey),
  n8n: () => !!config.n8nBaseUrl,
};
