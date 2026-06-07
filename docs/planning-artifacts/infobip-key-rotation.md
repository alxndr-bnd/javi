# Plan: rotate leaked Infobip API key (soon)

**Why:** the Infobip API key was pasted into a chat/log during setup and must be treated as
compromised. Prod actively sends Viber/SMS with it, so a leaked key = someone could send on
our sender (`IBSelfServe`) and burn the trial balance. Rotate at the next convenient window.

**Scope:** secret `javi-infobip-key` in GCP Secret Manager (project `serbito`), consumed by
Cloud Run service `javi` as env `INFOBIP_API_KEY`. See [[javi-infobip]].

## Steps

- [ ] In the Infobip portal → API keys: create a NEW key (same permissions), then **disable
      / delete the old (leaked) one**.
- [ ] Add a new version to Secret Manager (mind the trailing-newline gotcha — pipe with
      `printf %s` / `tr -d '\n'`, never `echo`; past Maps-key bug was a `\n` in the header):
      `printf %s "<NEW_KEY>" | gcloud secrets versions add javi-infobip-key --data-file=- --project=serbito`
- [ ] Confirm the latest version is the new one; the service reads `:latest`, so the next
      deploy/restart picks it up. Trigger a tagged deploy (or restart the revision) to apply.
- [ ] Smoke-test: send one real Viber to a verified number from the cabinet → status SENT.
- [ ] Revoke the old key only after the smoke test passes.

## Notes
- Quota counter (`FREE_QUOTA_VIBER/SMS`) is independent of the key — no change needed here.
- Optional follow-up: scrub the leaked value from any local logs/transcripts.

## Progress
- (pending — scheduled "soon" per owner, 2026-06-07)
