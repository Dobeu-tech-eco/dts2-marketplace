// Personal knowledge store: REST API + remote MCP endpoint on Cloudflare Workers + D1.
// Zero dependencies. Every request needs `Authorization: Bearer <KNOWLEDGE_TOKEN>`.

interface D1Result<T> {
  results: T[];
}
interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  all<T = Record<string, unknown>>(): Promise<D1Result<T>>;
  first<T = Record<string, unknown>>(): Promise<T | null>;
  run(): Promise<unknown>;
}
interface D1Database {
  prepare(query: string): D1PreparedStatement;
}
export interface Env {
  DB: D1Database;
  KNOWLEDGE_TOKEN?: string;
}

type Kind = "preference" | "term" | "learning";
interface Entry {
  key: string;
  kind: Kind;
  value: string;
  aliases: string[];
  tags: string[];
  updated: string;
  by: string;
}
interface Row {
  key: string;
  kind: Kind;
  value: string;
  aliases: string;
  tags: string;
  updated: string;
  by: string;
}
type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
type Obj = Record<string, unknown>;

class HttpError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

const KINDS: readonly Kind[] = ["preference", "term", "learning"];
const KEY_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const MAX_VALUE = 20000;
const MAX_LIST = 32;
const MAX_ITEM = 64;
const MIN_TOKEN = 3;
const SERVER_NAME = "dts2-knowledge";
const SERVER_VERSION = "1.0.0";
const PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"];
const TOOL_NOTE =
  "Personal knowledge store. Use only when the user explicitly asks about their stored preferences/glossary or during setup.";

// Secret guard: the same rules as scripts/knowledge.py.
const SECRET_NAME_PARTS = [
  "token", "password", "passwd", "secret", "api_key", "apikey", "api-key",
  "private_key", "private-key", "credential",
];
const SECRET_VALUE_RES: RegExp[] = [
  /sk-[A-Za-z0-9_-]{16,}/,
  /gh[pousr]_[A-Za-z0-9]{20,}/,
  /github_pat_/,
  /xox[abprs]-/,
  /AKIA[0-9A-Z]{16}/,
  /-----BEGIN/,
  /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\./,
];
const SECRET_MESSAGE = "refused: looks like a secret; the knowledge store is for preferences and glossary only";

function looksSecretName(text: string): boolean {
  const lower = text.toLowerCase();
  return SECRET_NAME_PARTS.some((part) => lower.includes(part));
}

function looksSecretValue(text: string): boolean {
  if (SECRET_VALUE_RES.some((re) => re.test(text))) return true;
  return text
    .split(/\s+/)
    .some((tok) => tok.length >= 32 && /[A-Za-z]/.test(tok) && /\d/.test(tok));
}

function guardSecrets(entry: Entry): void {
  const names = [entry.key, ...entry.aliases];
  if (names.some(looksSecretName) || looksSecretValue(entry.value)) {
    throw new HttpError(422, SECRET_MESSAGE);
  }
}

// ---------- auth ----------

async function digest(text: string): Promise<Uint8Array> {
  const data = new TextEncoder().encode(text);
  return new Uint8Array(await crypto.subtle.digest("SHA-256", data));
}

async function tokenMatches(given: string, expected: string): Promise<boolean> {
  const [a, b] = await Promise.all([digest(given), digest(expected)]);
  let diff = a.length ^ b.length;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ (b[i] ?? 0);
  return diff === 0;
}

async function authorized(request: Request, env: Env): Promise<boolean> {
  const expected = env.KNOWLEDGE_TOKEN;
  if (!expected) return false;
  const header = request.headers.get("Authorization") ?? "";
  const match = /^Bearer\s+(.+)$/i.exec(header);
  return match ? tokenMatches(match[1].trim(), expected) : false;
}

// ---------- helpers ----------

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...headers },
  });
}

function nowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function parseList(raw: string): string[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function toEntry(row: Row): Entry {
  return {
    key: row.key,
    kind: row.kind,
    value: row.value,
    aliases: parseList(row.aliases),
    tags: parseList(row.tags),
    updated: row.updated,
    by: row.by,
  };
}

function sortEntries(entries: Entry[]): Entry[] {
  return entries.sort((a, b) =>
    a.kind === b.kind ? (a.key < b.key ? -1 : a.key > b.key ? 1 : 0) : KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind),
  );
}

async function allEntries(env: Env, kind?: string | null): Promise<Entry[]> {
  const stmt = kind
    ? env.DB.prepare('SELECT "key", kind, value, aliases, tags, updated, "by" FROM entries WHERE kind = ?').bind(kind)
    : env.DB.prepare('SELECT "key", kind, value, aliases, tags, updated, "by" FROM entries');
  const { results } = await stmt.all<Row>();
  return sortEntries(results.map(toEntry));
}

function checkKind(kind: unknown): Kind {
  if (typeof kind === "string" && (KINDS as readonly string[]).includes(kind)) return kind as Kind;
  throw new HttpError(400, `kind must be one of: ${KINDS.join(", ")}`);
}

function checkKey(key: unknown): string {
  if (typeof key === "string" && KEY_RE.test(key)) return key;
  throw new HttpError(400, "key must match ^[a-z0-9][a-z0-9._-]{0,63}$");
}

function checkList(raw: unknown, label: string): string[] {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw) || raw.length > MAX_LIST) throw new HttpError(400, `${label} must be a list of up to ${MAX_LIST} strings`);
  return raw.map((item) => {
    if (typeof item !== "string" || !item.trim() || item.length > MAX_ITEM) {
      throw new HttpError(400, `${label} items must be non-empty strings up to ${MAX_ITEM} characters`);
    }
    return item.trim();
  });
}

function buildEntry(key: string, body: Obj, fallbackUpdated: string): Entry {
  const value = typeof body.value === "string" ? body.value.trim() : "";
  if (!value || value.length > MAX_VALUE) throw new HttpError(400, `value must be a non-empty string up to ${MAX_VALUE} characters`);
  const updated = typeof body.updated === "string" && ISO_RE.test(body.updated) ? body.updated : fallbackUpdated;
  const by = typeof body.by === "string" ? body.by.trim().slice(0, MAX_ITEM) : "";
  return {
    key: checkKey(key),
    kind: body.kind === undefined ? "preference" : checkKind(body.kind),
    value,
    aliases: checkList(body.aliases, "aliases"),
    tags: checkList(body.tags, "tags"),
    updated,
    by,
  };
}

// ---------- store operations ----------

async function findEntry(env: Env, keyOrAlias: string): Promise<Entry | null> {
  const row = await env.DB.prepare(
    'SELECT "key", kind, value, aliases, tags, updated, "by" FROM entries WHERE "key" = ?',
  ).bind(keyOrAlias).first<Row>();
  if (row) return toEntry(row);
  const wanted = keyOrAlias.toLowerCase();
  const entries = await allEntries(env);
  return entries.find((e) => e.aliases.some((a) => a.toLowerCase() === wanted)) ?? null;
}

async function putEntry(env: Env, entry: Entry): Promise<Entry> {
  guardSecrets(entry);
  await env.DB.prepare(
    'INSERT INTO entries ("key", kind, value, aliases, tags, updated, "by") VALUES (?, ?, ?, ?, ?, ?, ?) ' +
      'ON CONFLICT("key") DO UPDATE SET kind = excluded.kind, value = excluded.value, aliases = excluded.aliases, ' +
      'tags = excluded.tags, updated = excluded.updated, "by" = excluded."by"',
  ).bind(entry.key, entry.kind, entry.value, JSON.stringify(entry.aliases), JSON.stringify(entry.tags), entry.updated, entry.by).run();
  return entry;
}

async function removeEntry(env: Env, key: string): Promise<boolean> {
  const existing = await env.DB.prepare('SELECT "key" FROM entries WHERE "key" = ?').bind(key).first();
  if (!existing) return false;
  await env.DB.prepare('DELETE FROM entries WHERE "key" = ?').bind(key).run();
  return true;
}

function matchesText(entry: Entry, text: string): boolean {
  const needle = text.toLowerCase();
  const haystacks = [entry.key, entry.value, ...entry.aliases, ...entry.tags];
  return haystacks.some((h) => h.toLowerCase().includes(needle));
}

async function findEntries(env: Env, text: string, kind?: string | null): Promise<Entry[]> {
  if (kind) checkKind(kind);
  return (await allEntries(env, kind)).filter((e) => matchesText(e, text));
}

async function buildContext(env: Env, repo: string): Promise<Obj> {
  const entries = await allEntries(env);
  const haystack = repo.toLowerCase();
  const matches = entries
    .filter((e) => e.kind === "term")
    .filter((e) =>
      [e.key, ...e.aliases, ...e.tags].some((tok) => tok.length >= MIN_TOKEN && haystack.includes(tok.toLowerCase())),
    )
    .map((e) => e.key);
  return {
    store: "cloudflare",
    preferences: entries.filter((e) => e.kind === "preference"),
    terms: entries.filter((e) => e.kind === "term"),
    repo_matches: haystack ? matches : [],
  };
}

async function buildMeta(env: Env): Promise<Obj> {
  const owner = await env.DB.prepare('SELECT value FROM meta WHERE "key" = ?').bind("owner").first<{ value: string }>();
  const { results } = await env.DB.prepare("SELECT kind, COUNT(*) AS n FROM entries GROUP BY kind").all<{ kind: string; n: number }>();
  const counts: Record<string, number> = { preference: 0, term: 0, learning: 0 };
  for (const row of results) counts[row.kind] = row.n;
  return { backend: "cloudflare-d1", server: SERVER_NAME, version: SERVER_VERSION, owner: owner?.value ?? null, counts };
}

// ---------- REST API ----------

async function readBody(request: Request): Promise<Obj> {
  try {
    const body: unknown = await request.json();
    if (body && typeof body === "object" && !Array.isArray(body)) return body as Obj;
  } catch {
    // fall through
  }
  throw new HttpError(400, "body must be a JSON object");
}

async function handleApi(request: Request, env: Env, url: URL): Promise<Response> {
  const parts = url.pathname.split("/").filter(Boolean); // ["api", ...]
  const method = request.method;
  if (parts[1] === "meta" && parts.length === 2 && method === "GET") return json(await buildMeta(env));
  if (parts[1] === "context" && parts.length === 2 && method === "GET") {
    return json(await buildContext(env, url.searchParams.get("repo") ?? ""));
  }
  if (parts[1] !== "entries") throw new HttpError(404, "not found");
  if (parts.length === 2) {
    if (method !== "GET") throw new HttpError(405, "method not allowed");
    const kind = url.searchParams.get("kind");
    if (kind) checkKind(kind);
    const q = url.searchParams.get("q");
    const entries = q ? await findEntries(env, q, kind) : await allEntries(env, kind);
    return json({ entries });
  }
  if (parts.length !== 3) throw new HttpError(404, "not found");
  const key = decodeURIComponent(parts[2]);
  if (method === "GET") {
    const entry = await findEntry(env, key);
    if (!entry) throw new HttpError(404, `no entry: ${key}`);
    return json(entry);
  }
  if (method === "PUT") {
    const body = await readBody(request);
    if (typeof body.key === "string" && body.key !== key) throw new HttpError(400, "body key does not match path");
    return json(await putEntry(env, buildEntry(key, body, nowIso())));
  }
  if (method === "DELETE") {
    if (!(await removeEntry(env, key))) throw new HttpError(404, `no entry: ${key}`);
    return json({ deleted: key });
  }
  throw new HttpError(405, "method not allowed");
}

// ---------- MCP (streamable HTTP, JSON responses only) ----------

interface Tool {
  name: string;
  description: string;
  inputSchema: Obj;
  run: (env: Env, args: Obj) => Promise<unknown>;
}

const STR = { type: "string" };
const KIND_PROP = { type: "string", enum: [...KINDS] };
const LIST_PROP = { type: "array", items: STR };

function argString(args: Obj, name: string): string {
  const v = args[name];
  if (typeof v !== "string" || !v) throw new HttpError(400, `${name} is required`);
  return v;
}

const TOOLS: Tool[] = [
  {
    name: "knowledge_get",
    description: `${TOOL_NOTE} Get one entry by key or alias.`,
    inputSchema: { type: "object", properties: { key: STR }, required: ["key"] },
    run: async (env, args) => {
      const key = argString(args, "key");
      const entry = await findEntry(env, key);
      if (!entry) throw new HttpError(404, `no entry: ${key}`);
      return entry;
    },
  },
  {
    name: "knowledge_find",
    description: `${TOOL_NOTE} Case-insensitive substring search over key, aliases, tags and value.`,
    inputSchema: { type: "object", properties: { text: STR, kind: KIND_PROP }, required: ["text"] },
    run: async (env, args) => ({
      entries: await findEntries(env, argString(args, "text"), typeof args.kind === "string" ? args.kind : null),
    }),
  },
  {
    name: "knowledge_list",
    description: `${TOOL_NOTE} List entries, optionally of one kind.`,
    inputSchema: { type: "object", properties: { kind: KIND_PROP } },
    run: async (env, args) => {
      const kind = typeof args.kind === "string" ? args.kind : null;
      if (kind) checkKind(kind);
      return { entries: await allEntries(env, kind) };
    },
  },
  {
    name: "knowledge_set",
    description: `${TOOL_NOTE} Create or overwrite an entry. Secrets are refused.`,
    inputSchema: {
      type: "object",
      properties: { key: STR, value: STR, kind: KIND_PROP, aliases: LIST_PROP, tags: LIST_PROP, by: STR },
      required: ["key", "value"],
    },
    run: async (env, args) => putEntry(env, buildEntry(argString(args, "key"), { ...args, updated: undefined }, nowIso())),
  },
  {
    name: "knowledge_rm",
    description: `${TOOL_NOTE} Delete an entry by key.`,
    inputSchema: { type: "object", properties: { key: STR }, required: ["key"] },
    run: async (env, args) => {
      const key = argString(args, "key");
      if (!(await removeEntry(env, key))) throw new HttpError(404, `no entry: ${key}`);
      return { deleted: key };
    },
  },
  {
    name: "knowledge_context",
    description: `${TOOL_NOTE} Preferences, glossary terms and the terms matching a repository name or remote URL.`,
    inputSchema: { type: "object", properties: { repo: STR } },
    run: async (env, args) => buildContext(env, typeof args.repo === "string" ? args.repo : ""),
  },
];

function rpcResult(id: Json, result: unknown): Obj {
  return { jsonrpc: "2.0", id, result };
}

function rpcError(id: Json, code: number, message: string): Obj {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

async function callTool(env: Env, params: Obj): Promise<Obj> {
  const tool = TOOLS.find((t) => t.name === params.name);
  if (!tool) throw new HttpError(400, `unknown tool: ${String(params.name)}`);
  const args = params.arguments && typeof params.arguments === "object" ? (params.arguments as Obj) : {};
  try {
    const out = await tool.run(env, args);
    return { content: [{ type: "text", text: JSON.stringify(out, null, 2) }], isError: false };
  } catch (err) {
    if (err instanceof HttpError) return { content: [{ type: "text", text: err.message }], isError: true };
    throw err;
  }
}

async function handleRpc(env: Env, msg: Obj): Promise<Obj | null> {
  const isNotification = !("id" in msg);
  const id = (isNotification ? null : msg.id) as Json;
  if (msg.jsonrpc !== "2.0" || typeof msg.method !== "string") return rpcError(id, -32600, "invalid request");
  const params = (msg.params && typeof msg.params === "object" ? msg.params : {}) as Obj;
  if (isNotification) return null;
  switch (msg.method) {
    case "initialize": {
      const asked = typeof params.protocolVersion === "string" ? params.protocolVersion : "";
      return rpcResult(id, {
        protocolVersion: PROTOCOL_VERSIONS.includes(asked) ? asked : PROTOCOL_VERSIONS[0],
        capabilities: { tools: {} },
        serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
      });
    }
    case "ping":
      return rpcResult(id, {});
    case "tools/list":
      return rpcResult(id, {
        tools: TOOLS.map(({ name, description, inputSchema }) => ({ name, description, inputSchema })),
      });
    case "tools/call":
      try {
        return rpcResult(id, await callTool(env, params));
      } catch (err) {
        if (err instanceof HttpError) return rpcError(id, -32602, err.message);
        throw err;
      }
    default:
      return rpcError(id, -32601, `method not found: ${msg.method}`);
  }
}

async function handleMcp(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") {
    return json({ error: "this endpoint accepts POST only" }, 405, { Allow: "POST" });
  }
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return json(rpcError(null, -32700, "parse error"), 400);
  }
  if (Array.isArray(payload)) {
    const replies = (
      await Promise.all(payload.map((m) => handleRpc(env, (m ?? {}) as Obj)))
    ).filter((r): r is Obj => r !== null);
    return replies.length ? json(replies) : new Response(null, { status: 202 });
  }
  const reply = await handleRpc(env, (payload ?? {}) as Obj);
  return reply ? json(reply) : new Response(null, { status: 202 });
}

// ---------- entry point ----------

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (!(await authorized(request, env))) {
      return json({ error: "unauthorized" }, 401, { "WWW-Authenticate": 'Bearer realm="dts2-knowledge"' });
    }
    const url = new URL(request.url);
    try {
      if (url.pathname === "/mcp") return await handleMcp(request, env);
      if (url.pathname.startsWith("/api/")) return await handleApi(request, env, url);
      throw new HttpError(404, "not found");
    } catch (err) {
      if (err instanceof HttpError) return json({ error: err.message }, err.status);
      return json({ error: "internal error" }, 500);
    }
  },
};
