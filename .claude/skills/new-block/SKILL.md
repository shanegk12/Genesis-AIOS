---
name: new-block
description: Use when adding a new block type to the GK12 Platform lesson editor, or when Shane says "new block type", "add a block", or "/new-block". Full checklist across types, editor, renderer, settings, and the QC route, in order. Missing a step causes runtime errors or silent failures.
---

# /new-block

Add a new block type to the GK12 Platform lesson editor. Follow every step in order — missing one causes runtime errors or silent failures.

## Required information before starting

Ask the user for:
- Block type key (e.g. `quiz`, `timeline`) — must be lowercase kebab, no spaces
- What data fields it stores (text? html? images? list items?)
- Does it contain prose text the user might want to style? (yes → add to typography system)

---

## Checklist

### 1. `src/types/index.ts`

- Add the key to the `BlockType` union
- Define a `*BlockData` interface (e.g. `QuizBlockData`)
- Add a discriminated union arm to `Block` (`| { id: string; type: "quiz"; data: QuizBlockData; meta: BlockMeta }`)
- If the block has prose/text content: add its key to `TypographyBlockType`

### 2. `src/components/admin/blocks/*Block.tsx`

Create the editor component. Follow the pattern of a similar existing block. Key rules:
- Accept `({ block, onChange })` props
- Use `MiniEditor` for any rich-text html fields — pass `lessonId` prop
- Use `uploadLessonImage` from `@/lib/storage` for any image uploads
- Never use `getSignedUrl` — use download token URLs via the `/api/admin/images` route or `uploadLessonImage`

### 3. `src/components/admin/BlockCanvasEditor.tsx`

- Add the new type to the block picker list (search for `BlockPicker`)
- Add a `case` to `renderBlockEditor()` switch
- Add a `case` to `getBlockSummary()` in `src/app/api/admin/qc/request/route.ts` (step 6)
- If the block appears in the QC dot summary, add it there too

### 4. `src/components/lesson/LessonRenderer.tsx`

- Write a `*Block` renderer function
- If it has prose text: add `const typo = typoStyle(useContext(TypographyCtx), "block-key")` and apply `style={typo}` to the outermost text container
- Wrap all `dangerouslySetInnerHTML` calls with the `h()` helper (runs `processMath`)
- Add a `case "block-key":` to the main `switch` in `renderBlock()`

### 5. `src/components/admin/settings/BlockDefaultsSettings.tsx`

If the block has prose text, add an entry to `TYPO_BLOCKS`:
```ts
{ key: "block-key", label: "Human-readable label" },
```

### 6. `src/app/api/admin/qc/request/route.ts`

Add a `case` to `getBlockSummary()`:
```ts
case "block-key": return block.data.someTextField?.slice(0, 300) ?? block.type;
```

### 7. `firestore.rules` (only if new Firestore collection)

If the block introduces a new top-level collection, add an `isAdmin()` rule. Deploy immediately:
```
firebase deploy --only firestore:rules
```

---

## Gotchas

- `TypographyBlockType` union lives in `src/types/index.ts` — the settings component and renderer both import from there
- Firebase Storage: always use download token URLs. Pattern from `src/app/api/admin/images/route.ts`
- New block types must be handled in ALL four files or the editor/renderer will throw a runtime switch-exhaustion error
- After adding, verify in the block picker (admin editor) and lesson preview (student renderer)
