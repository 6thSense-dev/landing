# Contributor region enrollment and SMS verification

Identity infrastructure pass: 2026-09-14; mobile pilot status updated 2026-09-15. Firebase is not required. Cognito manages phone
verification and credentials; contributor documents remain in the private
`6thsense-contributor-records` bucket. No password, OTP, or session token belongs
in an S3 object, camera configuration, analytics event, or application log.

## Region policy

| Registration code | Country | Upload region tag | Collection | Currency / accepted hour |
| --- | --- | --- | --- | --- |
| `Korea666` | `KR` (+82) | `korea` | `korea-contributors` | KRW 11,000 |
| `China666` | `CN` (+86) | `china` | `china-contributors` | CNY; rate unset |
| `Vietnam666` | `VN` (+84) | `vietnam` | `vietnam-contributors` | VND; rate unset |
| `India666` | `IN` (+91) | `india` | `india-contributors` | INR; rate unset |

These are the four configured codes. Matching ignores case and surrounding
spaces. `ko2026` has been retired; `area666` is not an additional shared code.
All four destinations use `6thsense-raw` with the country-specific tags above.
An unset rate is unknown, never zero or a fallback to Korea's rate. Public
registration remains closed for all four countries.

The code selects the collection policy. It is a public routing label, not a
secret invitation or authorization to upload. The server validates it and pins
an immutable routing version (`kr-2026-v1`, `cn-2026-v1`, `vn-2026-v1`, or
`in-2026-v1`) to the Cognito account. Korea's existing routing version, collection
and rate are preserved across this code change. The registry
is `infra/contributor-regions.json` in Catalog and is packaged with the signup
Lambda. Synapse carries identical snapshots under `services/contributor-identity/`
and `src/lib/contributor/region-policy.json`; tests check their equality.

The app normalizes a local mobile number using the code-selected country:
Korean `010…` → `+8210…`, mainland Chinese `138…` → `+86138…`, Vietnamese `091…`
→ `+8491…`, and Indian `987…` → `+91987…`. For sign-in, resend and confirmation,
pass the canonical international number or explicitly provide the selected
country; a bare local number is never guessed. Cognito's signup gate independently
requires the international form and matching country/routing version. Validation
covers basic consumer-mobile prefixes and length, not all carrier allocations or
line types. Wrong-country numbers, unknown codes and mismatched versions are
rejected. SMS confirms control of a
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

The four-code update changes the version-pinned signup artifact only. It does
not replace the Cognito pool or app client, open registration, or alter existing
camera uploads.
The update reached `UPDATE_COMPLETE` and was verified on 2026-09-14 at 17:53 UTC:
the installed artifact contains the exact four-code registry, pool/client IDs
are unchanged, and a live gate invocation still returns `registration_not_open`.

- Pool: `us-west-2_mZ3Sz9xvE`
- Public Synapse client: `7c90capng6klmt2h1uhjnm919j` (no client secret)
- Issuer: `https://cognito-idp.us-west-2.amazonaws.com/us-west-2_mZ3Sz9xvE`
- General registration: closed. AWS sandbox SMS delivery: verified on 2026-09-14.
  The prepared [mobile pilot](CONTRIBUTOR-MOBILE-PILOT.md) is restricted to that verified Korean destination. The mobile UI and account API are connected in source; actual Cognito signup and the complete hardware/payment trial still need validation.

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

Country delivery remains separate from code configuration. AWS requires approved
SMS templates for China; sender-ID registration requirements also apply to
Vietnam and to the applicable Indian route. Confirm the sending route and its
requirements with AWS, then test the actual Cognito flow in each launch country.
Do not treat the Korean sandbox test as delivery evidence for other countries.

Cognito confirmation, resend, password sign-in, and current-user attribute reads
are implemented in Synapse `src/lib/contributor/registration.ts`. Provider
errors become fixed error codes; no raw response body reaches the UI. The
confirmation call forbids alias reassignment. An unverified or foreign phone
cannot produce the client's `phone_verified` display state.

The pilot's `LiveContributor.tsx` now uses this module and the authenticated
contributor API; preview consent and earnings stay separate. The backend checks
issuer, client ID, token use and subject, then calls Cognito GetUser to verify
the access token and current phone/routing attributes. Staff cookies cannot
authenticate a contributor. The completed app/hardware/payment trial is still
pending; connecting the UI is not delivery evidence.

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
The current mobile pilot instead uses supervised camera approval and manual SD-card offload into the existing raw layout. Its scanner checks trusted capture time against stored assignment intervals; it does not provision broker entitlements or deploy firmware.

## Verification and remaining rollout

Local tests cover server code/phone validation, closed registration, prevention
of client verification claims, real SDK signing with fake credentials, rejection
of caller-chosen destinations, malformed assignment refusal, OTP failures and
provider verification state. TypeScript and lint checks cover the modified
Synapse source. Separately, the controlled AWS sandbox SMS test was verified
on 2026-09-14 at 17:45 UTC. That establishes delivery to the authorized handset;
the Cognito signup flow and deployed-camera broker path still need live tests.

Recorded checks after the four-code update: 21 Python signup tests and 149 targeted Synapse/broker tests
passed; Synapse TypeScript and targeted ESLint passed. CloudFormation source,
Lambda artifact digest, immutable routing attribute and restricted mobile
write-attribute configuration were read back from AWS and verified.

## Launch work remaining

1. **SMS:** complete the actual Cognito signup/confirmation test, production SMS
   access and spend quota, per-country sender/template setup, and delivery tests.
2. **Real app onboarding:** exercise the connected pilot UI and contributor
   service with a user-created account, publish approved regional terms and
   verify durable consent/export. The separate preview remains sample data.
3. **Camera ownership and uploads:** test the implemented supervised claims and
   capture-time assignment history on real hardware, including delayed SD-card
   uploads after reassignment. Broker/firmware integration remains pending.
4. **Processing and ledgers:** run the recovery/QC workers, reconcile incomplete
   uploads and exclusions, deploy the revised Ops Raw/Clean/Users views, and
   verify the account-scoped dashboard against the uploaded and reviewed ledger.
5. **Payments:** agree China/Vietnam/India rates, exercise the implemented
   recipient onboarding/recovery and operator approval with real Wise tests, and
   reconcile delivery/returns before enabling automatic funding. The threshold
   remains strictly more than four hours of accumulated unpaid accepted time.
6. **End-to-end pilot:** complete one real account → camera → upload → Clean
   review → approved payout flow before opening general registration. Keep
   `sent` separate from confirmed `paid`; allow up to five business days after
   payout initiation in contributor-facing copy.

References: [Cognito SMS configuration](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-sms-settings.html),
[supported SMS countries](https://docs.aws.amazon.com/sms-voice/latest/userguide/phone-numbers-sms-by-country.html),
[pre-signup triggers](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-sign-up.html).
