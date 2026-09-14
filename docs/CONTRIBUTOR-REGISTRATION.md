# Contributor region enrollment and SMS verification

Implementation pass: 2026-09-14. Firebase is not required. Cognito manages phone
verification and credentials; contributor documents remain in the private
`6thsense-contributor-records` bucket. No password, OTP, or session token belongs
in an S3 object, camera configuration, analytics event, or application log.

## Region policy

| Registration code | Country | Upload region tag | Collection | Currency / accepted hour |
| --- | --- | --- | --- | --- |
| `ko2026` (case insensitive) | `KR` | `korea` | `korea-contributors` | KRW 11,000 |

The code selects the collection policy. It is a public routing label, not a
secret invitation or authorization to upload. The server validates it and pins
the immutable `kr-2026-v1` routing version to the Cognito account. The registry
is `infra/contributor-regions.json` in Catalog and is packaged with the signup
Lambda. Synapse carries the same registry under `services/contributor-identity/`.

The first supported phone format is a Korean `010` mobile number. The app
normalizes `010-1234-5678` to `+821012345678`; Cognito's signup gate independently
requires the international form. Foreign numbers, non-mobile formats, unknown
codes, and a mismatched routing version are rejected. SMS confirms control of a
phone number. It does not establish filming location, nationality, real-name
identity, terms acceptance, camera ownership, or bank ownership.

Do not edit an existing routing version to redirect historical recordings.
Changing a contributor's collection requires an explicit new enrollment and
effective-dated camera assignment. Registration code rotation does not reprice
or reassign past work.

## AWS identity resources

CloudFormation stack `sixthsense-contributor-identity` reached `CREATE_COMPLETE`
on 2026-09-14. The deployed template and Lambda artifact hash match the source.
The live signup-gate invocation rejects registration with `registration_not_open`.
No users have been created in this pool.

- Pool: `us-west-2_mZ3Sz9xvE`
- Public Synapse client: `7c90capng6klmt2h1uhjnm919j` (no client secret)
- Issuer: `https://cognito-idp.us-west-2.amazonaws.com/us-west-2_mZ3Sz9xvE`
- Registration: closed. AWS sandbox SMS delivery: verified on 2026-09-14.
  Cognito signup delivery: not tested. Mobile UI: not connected.

Catalog's `infra/contributor-identity.yaml` provisions a separate contributor
pool, public mobile app client, signup gate, scoped SMS role, and logging role in
account `194680606079`, `us-west-2`. The two company-account staff pools retain
their existing login and administrator-only registration settings.

The signup gate defaults to closed (`SignupEnabled=false`). A successful
CloudFormation deployment does not establish SMS delivery. Both inspected AWS
accounts were in the SMS sandbox with a USD 1 monthly spending limit. General
registration needs AWS SMS production access, an appropriate spend quota, a
Cognito signup delivery test, and launch abuse controls. No production-access
request has been submitted. On 2026-09-14, the operator authorized a Korean
mobile test, received the AWS sandbox verification SMS, and returned its code.
AWS accepted the code and lists the masked destination `+82 10-****-3400` as
`Verified`. The account remains in the sandbox. No OTP or full phone number is
stored in these notes; no contributor account was created for this test.

Cognito confirmation, resend, password sign-in, and current-user attribute reads
are implemented in Synapse `src/lib/contributor/registration.ts`. Provider
errors become fixed error codes; no raw response body reaches the UI. The
confirmation call forbids alias reassignment. An unverified or foreign phone
cannot produce the client's `phone_verified` display state.

This module is not yet connected to the in-memory contributor preview or a
released mobile screen. Keep preview consent and earnings separate. A server
integrating it must validate the access token's issuer, client ID, token use and
subject, then read current Cognito verification attributes. Client booleans or
decoded JWT payloads alone are not verification. Persist refresh credentials
only through the native secure store when the mobile auth UI is integrated.

## Upload policy

Synapse's upload broker accepts `routingVersion` and an opaque `assignmentId`
only from a server-provisioned entitlement row. The server resolves the route,
requires the configured destination to equal `6thsense-raw`, and signs these
object tags into the conditional S3 PUT:

```text
country=KR
region=korea
collection_id=korea-contributors
routing_version=kr-2026-v1
assignment_id=<opaque approved assignment ID>
```

Caller-supplied bucket and region fields cannot override the entitlement. No
name, phone number, contact address or bank information appears in the object
key or these tags. The broker's existing `t/<tenant>/<device>/...` key convention
is preserved. Tags and the `If-None-Match` condition are covered by SigV4.

Legacy operator entitlements remain supported without regional fields. A
partially configured regional assignment fails closed; it never falls back to
legacy access. New contributor accounts must not be given legacy operator
entitlements to bypass registration requirements. Only the backend may create
an entitlement after verified account linking, consent and camera proof.

The broker changes and its tagging IAM policy are source changes, not a live
firmware rollout. Deployed cameras still use their existing upload path. Before
cutover, prove capture-time assignment binding (including delayed uploads after
a camera changes hands), firmware support for the signed headers, one complete
upload, and preservation of these references/tags in Clean output manifests.
No historical source attribution, Raw objects or payment records are changed.

## Verification and remaining rollout

Local tests cover server code/phone validation, closed registration, prevention
of client verification claims, real SDK signing with fake credentials, rejection
of caller-chosen destinations, malformed assignment refusal, OTP failures and
provider verification state. TypeScript and lint checks cover the modified
Synapse source. Separately, the controlled AWS sandbox SMS test was verified
on 2026-09-14 at 17:45 UTC. That establishes delivery to the authorized handset;
the Cognito signup flow and deployed-camera broker path still need live tests.

Recorded checks: 15 Python signup tests and 140 targeted Synapse/broker tests
passed; Synapse TypeScript and targeted ESLint passed. CloudFormation source,
Lambda artifact digest, immutable routing attribute and restricted mobile
write-attribute configuration were read back from AWS and verified.

Next: test the Cognito signup SMS flow and complete production access, integrate
the real mobile registration screen and authenticated contributor service,
publish approved collection agreements, provision verified camera assignments,
then validate the upload path before enabling contributor registration.

References: [Cognito SMS configuration](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-sms-settings.html),
[supported SMS countries](https://docs.aws.amazon.com/sms-voice/latest/userguide/phone-numbers-sms-by-country.html),
[pre-signup triggers](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-sign-up.html).
