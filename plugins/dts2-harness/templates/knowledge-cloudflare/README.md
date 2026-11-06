# Knowledge store on Cloudflare (Worker + D1)

A small personal store for preferences and glossary terms that every device, and claude.ai on the web and phone,
can reach. It runs as one Cloudflare Worker with a D1 (SQLite) database in your own Cloudflare account. It has zero
npm dependencies: only `wrangler` is needed to deploy.

Use it for preferences and glossary only. Secrets are refused on write (same guard as the local store).

## Deploy

Run these from this directory. Use your own account; nothing here is deployed for you.

1. Log in (browser OAuth, no API token needed):
   `npx wrangler login`
2. Create the database, then paste the printed `database_id` into `wrangler.toml`:
   `npx wrangler d1 create dts2-knowledge`
3. Optionally change the `owner` label at the bottom of `schema.sql`, then apply the schema:
   `npx wrangler d1 execute dts2-knowledge --remote --file=schema.sql`
4. Generate a long random token and store it as a Worker secret (paste it when prompted):
   `openssl rand -hex 32`
   `npx wrangler secret put KNOWLEDGE_TOKEN`
5. Deploy:
   `npx wrangler deploy`

`wrangler` prints the Worker URL (`https://dts2-knowledge.<your-subdomain>.workers.dev`). Keep the token in a
password manager. Rotate it by running step 4 again.

Check it works:

```
curl -H "Authorization: Bearer $TOKEN" https://dts2-knowledge.<your-subdomain>.workers.dev/api/meta
```

## Auth

Every request needs `Authorization: Bearer <token>`, compared in constant time with the Worker secret
`KNOWLEDGE_TOKEN`. Without the secret set, every request is refused. OAuth through Cloudflare's
`workers-oauth-provider` is a later upgrade (it lets claude.ai sign in without a pasted token).

## REST API

| Method and path | Purpose |
| --- | --- |
| `GET /api/entries[?kind=&q=]` | list entries, optionally by kind and substring |
| `GET /api/entries/:key` | one entry, by key or alias (case-insensitive) |
| `PUT /api/entries/:key` | create or overwrite; body `{value, kind?, aliases?, tags?, by?, updated?}` |
| `DELETE /api/entries/:key` | remove |
| `GET /api/context?repo=<name-or-url>` | preferences, terms, and `repo_matches` for setup |
| `GET /api/meta` | owner label and counts |

Entry model: `key`, `kind` (`preference`, `term`, `learning`), `value`, `aliases`, `tags`, `updated`
(`YYYY-MM-DDTHH:MM:SSZ`), `by`. Keys match `^[a-z0-9][a-z0-9._-]{0,63}$`.

## Remote MCP

`POST /mcp` speaks MCP over streamable HTTP (JSON-RPC 2.0: `initialize`, `tools/list`, `tools/call`; JSON replies,
no streaming). Tools: `knowledge_get`, `knowledge_find`, `knowledge_list`, `knowledge_set`, `knowledge_rm`,
`knowledge_context`. Every tool description says: "Personal knowledge store. Use only when the user explicitly asks
about their stored preferences/glossary or during setup."

### Add it to claude.ai

1. Open claude.ai, then Settings, then Connectors, then "Add custom connector".
2. Name it, and enter the URL `https://dts2-knowledge.<your-subdomain>.workers.dev/mcp`.
3. Enable it per conversation when you want it.

Claude's custom connector form is built around OAuth. This Worker only checks a bearer token, so claude.ai may
refuse to connect until the OAuth upgrade above is done. Clients that let you set request headers (Claude Code,
`curl`, most MCP inspectors) work today with `Authorization: Bearer <token>`. Do not put the token in the URL.

## Use it from the harness

The plugin's `scripts/knowledge_cloudflare.py` syncs a local store directory with this Worker. Export the token
in your shell (it is never written to disk), then:

```
export DTS2_KNOWLEDGE_TOKEN=...
python3 scripts/knowledge_cloudflare.py --url https://dts2-knowledge.<your-subdomain>.workers.dev ping
python3 scripts/knowledge_cloudflare.py --url https://dts2-knowledge.<your-subdomain>.workers.dev pull ~/.dts2/knowledge
```

Sync pulls remote entries, then pushes local entries that are newer. The newer `updated` wins. Deletes do not sync.

## Free tier

Limits and pricing change. Check https://developers.cloudflare.com/workers/platform/pricing/ and
https://developers.cloudflare.com/d1/platform/pricing/ before relying on the free plan.

## Develop

Type-check without installing anything into this directory:
`npx -p typescript@5 tsc --noEmit --strict --target es2022 --module es2022 --moduleResolution bundler --lib es2022,webworker src/index.ts`
