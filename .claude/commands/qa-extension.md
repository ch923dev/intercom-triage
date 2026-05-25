---
description: Print the manual extension reload + verify checklist. There is no automated gate for the MV3 extension; this is the closest equivalent.
---

The Chrome extension has no automated test suite — Manifest V3 + a popup that talks to the operator's logged-in Intercom session is not test-harnessable without significant scaffolding (out of scope for this single-operator tool).

Instead, print this checklist to the user so they can verify the change end-to-end in Chrome. Don't try to run anything yourself — these steps require Chrome and an operator session.

```
[ ] chrome://extensions → find the unpacked extension → click reload
[ ] Open DevTools on the service worker — confirm no red errors at boot
[ ] Click the toolbar icon → popup opens
[ ] If the change touched intercom.js or background.js: click "Sync now" in the popup footer
[ ] Confirm:
    - Tickets render (or "no tickets" message if the workspace is empty)
    - Toolbar badge updates to the Urgent count within ~1s
    - No new red errors in the service worker console
[ ] If the change touched the popup UI: tab through Inbox / Resolved /
    Categories / Follow-ups / Proposals and confirm each renders
[ ] If the change touched manifest.json or host_permissions: Chrome shows
    a permission-delta confirm dialog on reload — read it carefully before
    accepting
```

Reference: `extension/CLAUDE.md` § 4 verification table for the per-file mapping (which checklist row maps to which file). Don't deviate from this — there is no other way to verify.
