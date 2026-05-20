#!/usr/bin/env node
const http = require('node:http');

const { handleRequest, createMemoryStore } = require('../src/index.js');

const requestedPort = Number(process.argv[2] || process.env.PORT || 8787);
const host = process.env.HOST || '127.0.0.1';

const env = {
  ALLOWED_ORIGINS: 'http://localhost:1313,http://127.0.0.1:1313,https://www.yuzhuohui.info',
  FEEDBACK_STORE: createMemoryStore(),
  FEEDBACK_VERSION: 'phase4-mvp',
};

function readRequestBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    const body = await readRequestBody(req);
    const address = server.address();
    const actualPort = address && typeof address === 'object' ? address.port : requestedPort;
    const requestUrl = `http://${host}:${actualPort}${req.url}`;
    const requestInit = {
      method: req.method,
      headers: req.headers,
    };
    if (body.length > 0) {
      requestInit.body = body;
    }

    const response = await handleRequest(new Request(requestUrl, requestInit), env);
    res.statusCode = response.status;
    for (const [key, value] of response.headers.entries()) {
      res.setHeader(key, value);
    }
    const responseBody = Buffer.from(await response.arrayBuffer());
    res.end(responseBody);
  } catch (error) {
    const message = error && error.stack ? error.stack : String(error);
    res.statusCode = 500;
    res.setHeader('content-type', 'text/plain; charset=utf-8');
    res.end(message);
  }
});

function shutdown() {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 2000).unref();
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

server.listen(requestedPort, host, () => {
  const address = server.address();
  const actualPort = address && typeof address === 'object' ? address.port : requestedPort;
  process.stdout.write(`listening:${host}:${actualPort}\n`);
});
