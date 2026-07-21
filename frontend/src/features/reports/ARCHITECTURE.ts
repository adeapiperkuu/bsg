/**
 * Architecture notes for PM `/reports` and client `/client/reports`.
 *
 * ## Product boundary
 * - `/reports` — PM workflow (draft → in_review → approved → sent / rejected)
 * - `/client/reports` — client published archive (sent only, read-only)
 *
 * ## Data flow
 * - PM inbox: `GET /communications` (lightweight, no bodies)
 * - PM detail: lazy `GET /communications/{id}`
 * - Generate: `POST /projects/{id}/communications/draft` (sync)
 * - Client archive: `GET /client/communications` (sent only)
 * - Nav prefetch: list only (`prefetchReportsNav`) — never detail fan-out
 *
 * ## Non-goals
 * - no polling, no background jobs, no auto-send/approve
 * - no `/agent-queries` from the frontend for generation
 */
export {};
