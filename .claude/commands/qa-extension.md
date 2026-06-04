---
description: Print the manual extension reload + verify checklist. There is no automated gate for the MV3 extension; this is the closest equivalent.
---

The Chrome extension has no automated test suite — a Manifest V3 popup is not test-harnessable without significant scaffolding (out of scope for this single-operator tool). The popup is a read-only board over the backend; ingestion is backend-side.

Instead, print this checklist to the user so they can verify the change end-to-end in Chrome. Don't try to run anything yourself — these steps require Chrome and a running backend on `:4000`.

```
[ ] chrome://extensions → find the unpacked extension → click reload
[ ] Open DevTools on the service worker — confirm no red errors at boot
[ ] Click the toolbar icon → popup opens
[ ] Confirm:
    - Tickets render (or "no tickets" message if the board is empty)
    - No requests to app.intercom.com in the Network tab (extension is backend-only)
    - Toolbar badge updates to the Urgent count within ~1s (with a poll interval set)
    - No new red errors in the service worker console
[ ] If the change touched the popup UI: tab through Inbox / Resolved /
    Categories / Follow-ups / Proposals and confirm each renders
[ ] If the change touched manifest.json or host_permissions: Chrome shows
    a permission-delta confirm dialog on reload — read it carefully before
    accepting
```

Reference: `extension/CLAUDE.md` § 4 verification table for the per-file mapping (which checklist row maps to which file). Don't deviate from this — there is no other way to verify.
