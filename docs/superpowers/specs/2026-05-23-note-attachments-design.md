# Note attachments — design spec

**Status:** approved (brainstorm) — implementation plan pending
**Date:** 2026-05-23
**Author:** Christian + Claude
**Stacks on:** `2026-05-23-time-tabled-notes-design.md` (this branch: `feat/time-tabled-notes`)

## Summary

Add file attachments to per-ticket notes. Two ownership scopes: each note
entry can carry attachments frozen with it (matches the append-only timeline
model), and each ticket has a separate "ticket files" bin not tied to any
entry. Files live on the local filesystem under `backend/data/attachments/`,
content-addressed by sha256 so identical uploads dedupe automatically. Soft
delete + nightly disk sweep keeps the DB authoritative while cleaning up
orphaned bytes.

Image attachments render as thumbnails inline beneath their owning entry or
in the ticket-bin zone; non-images render as file pills with filename, size,
and a download link.

## Motivation

Operator screenshots, log dumps, traces, and reproduction CSVs are common
during ticket investigation. Today the only way to share them is to paste
links into the freeform note. Native paste + drag-drop + file-picker upload
removes that friction. Per-entry attachments keep the audit trail tight:
the screenshot that justified the "Found bug X" finding lives with that
entry forever.

## Decisions (from brainstorm)

1. **Attachment scope:** images + arbitrary files (PDFs, CSVs, .txt logs).
2. **Storage:** local filesystem under `backend/data/attachments/`, DB rows
   carry metadata + path. Content-addressed by sha256 — dedup automatic.
3. **Binding:** both per-entry (frozen with entry) and per-ticket (separate
   bin) supported, via a single polymorphic owner column.
4. **Limits:** no hard caps. Single-operator local tool — no abuse vector.
   Caller-facing UI should hint at very-large files but doesn't block.
5. **Paste UX:** two explicit zones in the flyout. Ctrl+V in the new-entry
   textarea attaches to that entry-in-progress; drop/paste on the ticket-bin
   dropzone attaches to the per-ticket bin.
6. **Delete:** soft-delete + nightly disk sweep. Soft-deleted rows past a
   7-day window with no live siblings sharing the same sha256 get hard-
   deleted, file unlinked.
7. **Render:** image thumbnails inline (96px), file pills for non-images.
   Thumbnails generated server-side, cached on disk.

## Data model

### New table — `note_attachments`

```python
class NoteAttachment(Base):
    __tablename__ = "note_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_kind: Mapped[str] = mapped_column(Text, nullable=False)  # 'entry' | 'ticket'
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)    # str(entry.id) or ticket_id
    ticket_id: Mapped[str] = mapped_column(Text, nullable=False)   # always set for fast list-by-ticket
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)      # 64 hex chars
    stored_path: Mapped[str] = mapped_column(Text, nullable=False) # "ab/abc…def.png" relative to data/attachments/
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "owner_kind IN ('entry','ticket')",
            name="note_attachments_owner_kind_check",
        ),
        CheckConstraint("length(sha256) = 64", name="note_attachments_sha256_len_check"),
        CheckConstraint("size_bytes >= 0", name="note_attachments_size_nonneg_check"),
        Index("ix_note_attachments_owner", "owner_kind", "owner_id"),
        Index("ix_note_attachments_ticket", "ticket_id"),
        Index("ix_note_attachments_sha256", "sha256"),
    )
```

No FK to `note_entries` or `tickets` — matches the `followups` /
`note_entries` convention (ticket IDs owned by Intercom; entry rows can be
soft-deleted but should not break their attachments).

### Disk layout

```
backend/data/attachments/
  ab/abc123…def.png         ← content-addressed by sha256
  cd/cde456…789.pdf
  thumbs/
    abc123…def.webp         ← 256px-long-side WebP, generated on first request
```

Sharded by `sha256[:2]` to avoid one fat directory. Two uploads with the
same bytes share one disk file. The store-on-disk operation:

1. Read upload into a temp file, hash as you go.
2. If target path exists, skip the write.
3. Insert the row, commit.
4. On row insert failure: unlink the temp file (but only if the final
   target path is not already referenced by another live row).

## API

```
POST   /attachments                       multipart/form-data:
                                            file (binary)
                                            owner_kind ('entry' | 'ticket')
                                            owner_id (str)
                                            ticket_id (str)
                                          → 200 NoteAttachmentRead

GET    /attachments?ticket_id=...         list non-deleted for a ticket (both kinds)
                                          → 200 list[NoteAttachmentRead]

GET    /attachments/{id}/raw              stream bytes
                                          Content-Type: <mime>
                                          Content-Disposition: inline; filename="<filename>"

GET    /attachments/{id}/thumb            image: 256px-max-side WebP (cached on disk after first call)
                                          non-image: 404

DELETE /attachments/{id}                  soft-delete → {ok:true, deleted:true, id}
```

`NoteAttachmentRead` shape:

```json
{
  "id": 7,
  "owner_kind": "entry",
  "owner_id": "42",
  "ticket_id": "abc",
  "filename": "screenshot.png",
  "mime": "image/png",
  "size_bytes": 184729,
  "created_at": "2026-05-23T10:42:00Z",
  "raw_url": "/api/attachments/7/raw",
  "thumb_url": "/api/attachments/7/thumb"
}
```

`thumb_url` is `null` when `mime` does not start with `image/`.

`raw_url` / `thumb_url` paths are returned relative to the `/api` proxy so
the webapp consumes them without knowing backend host details.

## Sweep

Background loop in `app/main.py` next to the existing `_cache_sweep_loop`.
Runs once at boot, then every `ATTACHMENT_SWEEP_INTERVAL_SECONDS` (default
86400 = 24h).

Each pass:

1. Find rows with `deleted_at < now() - ATTACHMENT_GC_DAYS days` (default 7).
2. For each: count live (non-deleted) rows with the same `sha256`.
3. If zero live siblings → unlink `data/attachments/<stored_path>` AND the
   matching thumbnail at `thumbs/<sha256>.webp` if present. Hard-delete the
   row.
4. If live siblings exist → leave the disk file alone. Hard-delete the row.

Counter: `attachments_gc_total` (with `.files_unlinked` and `.rows_deleted`
labels). Logged on each non-empty pass.

## Frontend

### Types

```ts
export interface NoteAttachment {
  id: number;
  owner_kind: 'entry' | 'ticket';
  owner_id: string;
  ticket_id: string;
  filename: string;
  mime: string;
  size_bytes: number;
  created_at: string;
  raw_url: string;
  thumb_url: string | null;
}
```

### Store — `webapp/src/stores/attachments.ts`

```ts
useAttachmentsStore:
  map: Record<ticket_id, NoteAttachment[]>     // both kinds, non-deleted
  loadedTickets: Set<ticket_id>                 // lazy seed guard
  load(ticketId)                                // GET /attachments?ticket_id=… (no-op if loaded)
  upload(file, ownerKind, ownerId, ticketId)    // multipart POST; optimistic placeholder; replaces on resolve
  remove(id)                                    // optimistic soft-delete; rollback on failure
  byEntry(entryId): NoteAttachment[]
  byTicket(ticketId): NoteAttachment[]          // owner_kind === 'ticket' only
```

Lazy load (per ticket on flyout open) — avoids fetching every ticket's
attachments at app mount. Map persists across closes.

### Flyout — additions to `TicketFlyout.vue`

Existing Next-step notes section gains two new pieces:

**Ticket files zone** (new block above the timeline):

```
─ Ticket files ─
  [ Drop files, paste, or click to browse ]
  [thumb][thumb] [📄 trace.csv 88KB ↓]   [×]
```

A `<div>` with:
- `@dragover.prevent` + `@drop` → upload each `e.dataTransfer.files`
  immediately with `owner_kind='ticket', owner_id=ticket.id`.
- `@paste` (when focused) → same.
- `click` → opens hidden `<input type="file" multiple>`.

**Per-entry attachments** render under each timeline row using
`attachments.byEntry(entry.id)`. Same thumbnail / pill rendering.

**New-entry compose** — Ctrl+V or drag-drop on the textarea adds files to
local pending state:

```
[ textarea ]
[ pending attachments preview row ]   ← thumbs/pills with × to remove before submit
Timer: …
Reason: …
[Add entry]
```

On `Add entry`:
1. POST `/notes/entries` → returns new entry id.
2. Parallel POST each pending attachment with `owner_kind='entry',
   owner_id=String(new entry.id)`.
3. Resolve, reset form.

If any attachment upload fails the entry stays (it's already persisted) and
the failed attachment surfaces an inline error; user can retry.

**Render:**
- Images: 96px square thumbnail, `object-fit: cover`, click opens
  `raw_url` in new tab.
- Non-images: pill row showing `[icon] filename · sizeKB ↓`. Click pill =
  download (`raw_url`, opens in new tab, browser handles).
- `×` button on each attachment soft-deletes via `attachments.remove(id)`.

## Migration

Single Alembic revision 0009:

1. Create `note_attachments` table + indices + check constraints.
2. No data migration.
3. `downgrade` drops the table. Disk files left in place (operator can
   manually purge `data/attachments/` if desired).

Filesystem bootstrap on backend startup (lifespan hook):

```python
config.attachments_dir.mkdir(parents=True, exist_ok=True)
(config.attachments_dir / "thumbs").mkdir(parents=True, exist_ok=True)
```

## Dependencies

New backend dependency: `Pillow` (in `backend/requirements.txt`). Used only
for thumbnail generation. Add `[[tool.mypy.overrides]]` for PIL if stubs
missing.

## Tests

### Backend

`tests/test_attachments_service.py`:
- Upload happy path → row + disk file exist + on-disk bytes hash to
  reported sha256.
- Dedup: two uploads of same bytes → one disk file, two rows pointing at it.
- Soft-delete sets `deleted_at`, file stays on disk.
- Sweep: row past GC window with no live siblings → file unlinked + row
  hard-deleted.
- Sweep: row past GC window with a live sibling sharing sha256 → file
  kept, row hard-deleted.
- Thumb generation: PNG → WebP file at expected path; cached on second call.
- Non-image thumb request → 404.

`tests/test_attachments_api.py`:
- POST multipart with `owner_kind='entry'` returns row with correct fields.
- POST multipart with `owner_kind='ticket'` returns row with correct fields.
- GET list filtered by `ticket_id` returns both kinds; soft-deleted excluded.
- GET raw returns bytes + correct `Content-Type` + filename in
  `Content-Disposition`.
- GET thumb returns WebP for an image upload.
- GET thumb returns 404 for a text/plain upload.
- DELETE returns `{ok, deleted, id}` envelope and excludes row from
  subsequent list.
- POST missing required form field → 422.

### Webapp

`webapp/src/stores/attachments.spec.ts`:
- `load(ticketId)` populates map + marks loaded; second call is a no-op.
- `upload` shows optimistic placeholder with temp id < 0; replaces with
  server row on resolve.
- Failed upload rolls back the placeholder.
- `byEntry(id)` filters to `owner_kind='entry' && owner_id===String(id)`.
- `byTicket(ticketId)` filters to `owner_kind='ticket'` for that ticket.
- `remove(id)` optimistic; rolls back on rejection.

### Quality gates

Same as the time-tabled-notes spec — ruff + mypy + pytest + typecheck +
build + vitest. Pillow added to mypy overrides if no stubs.

## Rollout

- Single PR. Backend + webapp + Alembic migration + Pillow dep.
- Stacks on `feat/time-tabled-notes` since per-entry attachments reference
  `note_entries.id`. Merge both branches to `main` together.
- No feature flag — local single-operator tool.
- README API table updated with `/attachments` rows.

## Out of scope (YAGNI)

- Attachment editing / replace (delete + re-upload).
- Per-attachment versioning or history.
- EXIF stripping — single-operator local tool, no exfil risk.
- Antivirus scanning — same reason.
- Auth on `/raw` — backend is localhost-only.
- Resumable / chunked uploads.
- Bulk upload progress UI — one-by-one is fine for expected volumes.
- Chrome extension integration — extension does not surface notes today.
- Per-attachment size or count caps — single-operator tool, no abuse vector.
