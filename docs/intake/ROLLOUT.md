# Internal Catalog review rollout

This feature lives in the existing website portal, not the temporary Forge
workbench. It uses the existing session and `admin` database role. The feature
also requires the authenticated account to be `ronak@6thsense.dev` and the backend
flag `INTAKE_REVIEW_ENABLED=true`. It is disabled by default. No signup or login
request grants privileges based on an email address.

The initial packaged recording is synthetic, explicitly labelled in the UI.
Activity edits download native review proposals. They do not approve a dataset,
change collector credit or payment settlement, modify recordings, or run models.

## Deploy and enable

1. Review and merge the tested PR into `main`. Deploy both existing Railway
   frontend and backend services from that commit. Verify actual service
   deployment status; GitHub's deployment status may cover only one service.
   No migrations are added by this change; the existing backend startup command
   still executes its normal migration step.
2. On the actual backend host, with its existing database configuration, run
   `python -m app.cli_intake_admin`. This targets only Ronak's account. An active
   existing account is promoted to admin, its existing password is preserved,
   and old sessions are revoked on promotion. An existing admin is unchanged.
   An inactive or ambiguous identity is refused for explicit resolution.
3. If the account is absent, run `python -m app.cli_intake_admin --create` in an
   interactive backend terminal and supply a unique password through the hidden
   prompt. Do not put a password in source, a command argument, a PR, or logs.
4. Set backend `INTAKE_REVIEW_ENABLED=true`, redeploy the backend, and verify
   Ronak can sign in at the existing `/login` and open `/portal/intake-review`.
   Verify video, exact boundary editing, and proposal download in a browser.
5. Verify a guest, an ops user, and a different admin cannot fetch the activity,
   preview, or proposal endpoints. A hidden navigation link is not the access
   control: all those backend endpoints enforce the account and feature gate.

To disable the feature, unset `INTAKE_REVIEW_ENABLED` or set it to `false` and
redeploy the backend. This does not revoke the account's ordinary admin role.
Account revocation uses the existing account administration flow; it is a
separate action from hiding a feature.

## Current access dependency

On September 11, Forge had repository access but no Railway CLI login or
Railway/database deployment credentials. GitHub's latest successful deployment
pointed to project `ec20ebd8-12d0-4956-aefa-a9f9c7ff08a4`, environment
`3ac3c205-05eb-410d-acfb-332bb61f82bd` (`sixthsense / production`). Those records do
not grant backend terminal access. Provisioning and enabling must be verified
against the actual service; source tests do not establish a live account exists.
