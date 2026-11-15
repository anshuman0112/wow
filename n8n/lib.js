// Tiny helpers to describe n8n workflows in readable JS and export importable JSON.
import { randomUUID } from 'node:crypto';

export function workflow(name, nodes, edges, { active = false, id } = {}) {
  // Auto-layout: place nodes left→right in the order given, branching rows by `row`.
  const col = {};
  nodes.forEach(n => {
    const c = n._col ?? 0;
    n.position = [c * 260, (n._row ?? 0) * 180];
    delete n._col; delete n._row;
    col[n.name] = c;
  });
  const connections = {};
  for (const [from, to, output = 0] of edges) {
    connections[from] ??= { main: [] };
    while (connections[from].main.length <= output) connections[from].main.push([]);
    connections[from].main[output].push({ node: to, type: 'main', index: 0 });
  }
  return { ...(id ? { id } : {}), name, nodes, connections, active, settings: { executionOrder: 'v1' }, pinData: {}, meta: { templateCredsSetupCompleted: true } };
}

const base = (name, type, typeVersion, parameters, extra = {}) => ({ id: randomUUID(), name, type, typeVersion, parameters, ...extra });
const at = (node, col, row = 0) => Object.assign(node, { _col: col, _row: row });

export const webhook = (name, path, col, row, { respond = 'onReceived' } = {}) => at(base(name, 'n8n-nodes-base.webhook', 2, {
  httpMethod: 'POST', path, responseMode: respond, options: { allowedOrigins: '*' },
}, { webhookId: randomUUID() }), col, row);

export const schedule = (name, minutes, col, row) => at(base(name, 'n8n-nodes-base.scheduleTrigger', 1.2, {
  rule: { interval: [{ field: 'minutes', minutesInterval: minutes }] },
}), col, row);

export const code = (name, jsCode, col, row, extra = {}) => at(base(name, 'n8n-nodes-base.code', 2, { jsCode: jsCode.trim() }, extra), col, row);

export const ifTrue = (name, leftValue, col, row) => at(base(name, 'n8n-nodes-base.if', 2, {
  conditions: {
    options: { caseSensitive: true, leftValue: '', typeValidation: 'loose' },
    conditions: [{ id: randomUUID(), leftValue, rightValue: '', operator: { type: 'boolean', operation: 'true', singleValue: true } }],
    combinator: 'and',
  },
  options: {},
}), col, row);

export const wait = (name, seconds, col, row) => at(base(name, 'n8n-nodes-base.wait', 1.1, {
  resume: 'timeInterval', amount: seconds, unit: 'seconds',
}, { webhookId: randomUUID() }), col, row);

export const respond = (name, body, col, row) => at(base(name, 'n8n-nodes-base.respondToWebhook', 1.1, {
  respondWith: 'json', responseBody: body, options: { responseHeaders: { entries: [{ name: 'Access-Control-Allow-Origin', value: '*' }] } },
}), col, row);

// HTTP Request node. headers: {name: value}. body: n8n expression string producing JSON.
export function http(name, { method = 'GET', url, headers = {}, body, form, binaryIn, fileOut = false, continueOnFail = false, timeoutMs }, col, row) {
  const p = { method, url, options: timeoutMs ? { timeout: timeoutMs } : {} };
  const hs = Object.entries(headers);
  if (hs.length) { p.sendHeaders = true; p.headerParameters = { parameters: hs.map(([name, value]) => ({ name, value })) }; }
  if (body) { p.sendBody = true; p.specifyBody = 'json'; p.jsonBody = body; }
  if (form) { p.sendBody = true; p.contentType = 'form-urlencoded'; p.bodyParameters = { parameters: Object.entries(form).map(([name, value]) => ({ name, value })) }; }
  if (binaryIn) { p.sendBody = true; p.contentType = 'binaryData'; p.inputDataFieldName = binaryIn; }
  if (fileOut) p.options.response = { response: { responseFormat: 'file' } };
  return at(base(name, 'n8n-nodes-base.httpRequest', 4.2, p, continueOnFail ? { onError: 'continueRegularOutput' } : {}), col, row);
}

// Common header sets (values are read from n8n's environment, loaded from .env by scripts/start_n8n.js)
export const SUPA = {
  apikey: '={{ $env.SUPABASE_SERVICE_ROLE_KEY }}',
  Authorization: '=Bearer {{ $env.SUPABASE_SERVICE_ROLE_KEY }}',
  'Content-Type': 'application/json',
};
export const VAPI = { Authorization: '=Bearer {{ $env.VAPI_PRIVATE_KEY }}', 'Content-Type': 'application/json' };
export const GROQ = { Authorization: '=Bearer {{ $env.GROQ_API_KEY }}', 'Content-Type': 'application/json' };
