# Firebase Genkit — Reference for GK12 Platform

> Research compiled 2026-05-18. Verify package versions before implementing.

## What it is

Genkit is Google's open-source TypeScript (and Python alpha) framework for building production AI features. It wraps model calls in typed, observable, streaming-capable **flows** — the core primitive. It is not a model or a platform; it is an orchestration layer that sits between your app code and whatever AI models/tools you call.

Key differentiator from raw SDK calls: every flow execution is **automatically traced** with inputs, outputs, latency, token usage, and sub-call waterfall — visible in the Dev UI or stored in Firestore.

## Core concepts

| Concept | What it is |
|---------|------------|
| **Flow** | A typed async function (`defineFlow`) that Genkit traces, validates, and can stream. The unit of AI work. |
| **Action** | A simpler, non-flow unit (tool, retriever, indexer). Flows compose actions. |
| **Plugin** | Adapter that wires in a model provider, vector store, or platform integration. |
| **Prompt** | Dotprompt `.prompt` files — version-controlled, testable prompt templates with schema validation. |
| **Dev UI** | Local server (`:4000`) that lists all flows, lets you run them interactively, and shows traces. Run with `genkit start`. |

## Installation (Next.js / Node)

```bash
npm install genkit @genkit-ai/googleai
# Firebase plugin (tracing to Firestore, App Check):
npm install @genkit-ai/firebase
```

## Minimal flow example

```typescript
import { genkit } from "genkit";
import { googleAI, gemini25Flash } from "@genkit-ai/googleai";

const ai = genkit({ plugins: [googleAI()] });

export const tutorFlow = ai.defineFlow(
  {
    name: "tutorFlow",
    inputSchema: z.object({ question: z.string(), lessonContext: z.string() }),
    outputSchema: z.string(),
  },
  async ({ question, lessonContext }) => {
    const { text } = await ai.generate({
      model: gemini25Flash,
      system: "You are a tutor for Genesis K-12. Answer concisely and faithfully.",
      prompt: `Context: ${lessonContext}\n\nStudent question: ${question}`,
    });
    return text;
  }
);
```

Call from a Next.js API route: `await tutorFlow({ question, lessonContext })`

## Streaming (for chat UI)

```typescript
const { stream, response } = await ai.generateStream({
  model: gemini25Flash,
  prompt: userMessage,
});
for await (const chunk of stream) {
  res.write(chunk.text);
}
```

## Firebase plugin

```typescript
import { firebase } from "@genkit-ai/firebase";

const ai = genkit({
  plugins: [
    googleAI(),
    firebase(),   // traces → Firestore "genkit_traces" collection
  ],
});
```

Adds:
- Automatic trace storage in Firestore
- Flow endpoint auth via Firebase ID tokens
- App Check integration

## Model support (via plugins)

| Plugin | Models |
|--------|--------|
| `@genkit-ai/googleai` | Gemini 2.5 Flash, Gemini 2.5 Pro, Gemini 1.5 series |
| `@genkit-ai/vertexai` | Same Gemini models + Vertex-only Imagen, PaLM |
| `@genkit-ai/anthropic` (community) | Claude models |
| `@genkit-ai/ollama` | Local models (Llama, Mistral, etc.) |

Switching models is one line — same flow code, different `model:` argument.

## RAG (retrieval-augmented generation)

```typescript
// Define a retriever against a Firestore vector index
const lessonRetriever = ai.defineFirestoreRetriever({
  name: "lessons",
  firestore: getFirestore(),
  collection: "lessons",
  contentField: "content",
  vectorField: "embedding",
  embedder: textEmbeddingGecko,
  distanceMeasure: "COSINE",
});

// Use in a flow
const docs = await ai.retrieve({ retriever: lessonRetriever, query: question });
```

Requires Firestore vector search (GA as of 2025) — `gcloud firestore indexes composite create ...`

## Dotprompt — version-controlled prompts

Create `prompts/tutor.prompt`:
```
---
model: googleai/gemini-2.5-flash
input:
  schema:
    question: string
    lessonContext: string
---
You are a GK12 tutor. Answer based only on the lesson content below.

Lesson: {{lessonContext}}

Student: {{question}}
```

Load with: `const tutorPrompt = ai.prompt("tutor")`

Enables: prompt versioning in git, testing in Dev UI without code changes.

## Dev UI

```bash
npx genkit start -- npx ts-node src/flows/index.ts
# Opens http://localhost:4000
```

- Lists every `defineFlow` and `defineAction`
- Run any flow interactively with test input
- View full trace waterfall (model calls, tool calls, latency)
- Inspect prompt renders before they hit the model

## Genkit vs raw Gemini SDK (for GK12 decisions)

| | Raw Gemini SDK / REST | Genkit |
|---|---|---|
| Tracing/observability | None | Built-in, Firestore storage |
| Streaming | Manual SSE | `generateStream()` helper |
| Model swapping | Rewrite call sites | Change one `model:` arg |
| Prompt management | Strings in code | `.prompt` files, versioned |
| RAG | Build from scratch | `defineRetriever` pattern |
| Dev testing | `console.log` | Dev UI at :4000 |
| Overhead | Minimal | ~200ms cold start on Cloud Functions |

## Where Genkit fits in the GK12 stack

### High-value targets

1. **AI Tutor endpoint** (`/api/tutor/route.ts`) — currently a direct Gemini REST call. Wrapping in a Genkit flow gives streaming, tracing, and easy model swap. **Recommended next.**

2. **Lesson QC flow** — a Genkit flow that checks imported lesson HTML against a rubric (heading structure, placeholder detection, section count). Returns a typed QC report. Replaces the Python `format_qc_agent.py` long-term.

3. **Dev fix agent** — Genkit's tool-use support makes it easy to wire "read Firestore lesson → run Gemini fix → PATCH Firestore" as a single traced flow callable from admin.

### Not the right fit (keep in Python)

- Draft generation (`lesson_pipeline.py`) — Gemini with large prompts + Google Docs writes. Python ecosystem (googleapiclient, google-auth) is more mature here. No benefit from moving to Genkit.
- Platform import (`platform_import.py`) — pure data pipeline, no AI. Leave as-is.

## Packages as of mid-2026

```json
{
  "genkit": "^1.30",
  "@genkit-ai/google-genai": "^1.34",
  "@genkit-ai/vertexai": "^1.27",
  "@genkit-ai/firebase": "^1.32",
  "@genkit-ai/next": "^1.23",
  "zod": "^3.x"
}
```

Note: package name is `@genkit-ai/google-genai` (not `@genkit-ai/googleai`). Genkit hit 1.0 stable in Feb 2025 — not alpha/beta.

## Cloud Functions deployment

```typescript
import { onCallGenkit } from "@genkit-ai/firebase/functions";

export const tutorFlow = onCallGenkit(
  { authPolicy: hasClaim("role", "student") },
  async (input: { question: string; lessonContext: string }) => {
    // ... flow body
  }
);
```

`onCallGenkit` gives automatic streaming, App Check, and Firebase Auth policy enforcement.

## Firebase AI Monitoring

Enable with `enableFirebaseTelemetry()` in your Genkit config. Traces auto-export to GCP and appear in Firebase Console under "AI Monitoring" — shows latency, success rates, failed flows, and per-call input/output detail. Requires Blaze plan.

## Key limits / gotchas

- Flows run server-side only — keep in `src/lib/flows/` or `src/app/api/`, never in React components.
- Dev UI: `npx genkit start -- npx tsx src/flows/index.ts` — opens at `http://localhost:4000`
- Traces accumulate in Firestore `genkit_traces` — set a TTL or costs grow.
- Python Genkit SDK is alpha as of mid-2026 — do not use for production. Python pipeline stays on direct API calls.
- Vertex AI plugin required for Imagen (image generation); `@genkit-ai/google-genai` covers text/multimodal Gemini only.
- `FirestoreStreamManager` / `RtdbStreamManager` exist for durable long-running stream state — useful if the tutor chat needs to survive page refreshes.
