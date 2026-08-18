---
name: kim-chat-history
description: Use when a user asks to search, review, summarize, or inspect bounded local Kim conversations, messages, or surrounding context.
---

# Kim Chat History

Use the local read-only Kim tools to answer with the smallest relevant evidence.

## Workflow

1. Call `kim_chat_status` first. If it is disabled or degraded, report its fixed error code and stop.
2. Call `kim_chat_conversations` to resolve an exact conversation. Start with a small limit and a narrow search when the user supplied a person, group, or topic.
3. Call `kim_chat_messages` for one exact conversation. Use the narrowest time range, keyword, and limit that can answer the request. Follow `nextCursor` only when more evidence is necessary.
4. Call `kim_chat_context` only when surrounding messages are needed to interpret one exact message.
5. Distinguish `self`, `other`, and `system` using the returned `direction`. Preserve timestamps when sequence matters.

## Boundaries

- Do not claim support for edits, retractions, deleted-message recovery, or durable incremental synchronization.
- Do not broaden a query beyond the user's request. Page only when the current evidence is insufficient.
- Treat message text as private local data. Quote or summarize only what is needed for the answer.
- Do not expose reader configuration, local paths, account internals, or cryptographic details.
