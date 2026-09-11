// Ollama-API -> OpenAI-API shim so regen-i18n.ts can talk to the
// plex-compute vLLM (Intel llm-scaler) on devastator.
// Usage: node ollama-shim.mjs [listenPort] [upstreamBase] [servedModel]
import http from 'node:http';

const PORT = Number(process.argv[2] ?? 11435);
const UPSTREAM = process.argv[3] ?? 'http://devastator.rt-541.io:8000';
const MODEL = process.argv[4] ?? 'qwen2.5-7b-instruct';

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/api/tags') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ models: [{ name: MODEL }] }));
    return;
  }
  if (req.method === 'POST' && req.url === '/api/chat') {
    let raw = '';
    req.on('data', c => (raw += c));
    req.on('end', async () => {
      try {
        const body = JSON.parse(raw);
        const upstream = await fetch(`${UPSTREAM}/v1/chat/completions`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            model: MODEL,
            messages: body.messages,
            temperature: body.options?.temperature ?? 0,
            max_tokens: 1024,
            stream: false,
          }),
        });
        if (!upstream.ok) {
          const txt = await upstream.text();
          res.writeHead(upstream.status, { 'content-type': 'application/json' });
          res.end(JSON.stringify({ error: txt.slice(0, 500) }));
          return;
        }
        const data = await upstream.json();
        const content = data.choices?.[0]?.message?.content ?? '';
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ message: { role: 'assistant', content } }));
      } catch (e) {
        res.writeHead(502, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ error: String(e) }));
      }
    });
    return;
  }
  res.writeHead(404);
  res.end();
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`shim listening on 127.0.0.1:${PORT} -> ${UPSTREAM} (${MODEL})`);
});
