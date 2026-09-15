# Business sources in Collector operations

Version `0.0.8.0` adds operator-confirmed business provenance to Raw, Clean and
processing claims. Production rollout is in progress; this document describes
the implementation and does not establish completed media processing or cleanup.

Business footage keeps its decoded, retained and excluded time in Clean without
becoming an individual contributor's earnings. Settlement remains outside Ops:
this release provides neither a B2B invoice engine nor self-service business
onboarding.

## Maintenance registry

`app.core.ops_sources` reads the JSON object stored in `OpsSetting` under
`ops_source_attributions_v1`. The registry is maintained through controlled
database maintenance; there is no registration API, form or bundled writer.
A worker's manifest cannot establish business ownership by itself.

Each key is a full recording identity. Its value must match that existing
episode's `recording`, `device_id` and `session` exactly, and the episode must have
`wearer_id: null`. A mismatch requires reconciliation rather than assigning the
footage to the current camera holder. This example uses synthetic identifiers:

```json
{
  "ego_20260901_120000_ABC123": {
    "recording": "ego_20260901_120000_ABC123",
    "device_id": "ABC123",
    "session": "example-session",
    "counterparty": {
      "kind": "business",
      "id": "example-factory",
      "name": "Example factory",
      "country": "china",
      "payment_model": "b2b_contract"
    }
  }
}
```

The counterparty contains exactly those five fields. Its ID is 1–80 lowercase
letters, digits or hyphens, beginning with a letter or digit; its name is nonblank
and at most 200 characters. Country is one of `china`, `korea`, `vietnam` or
`india`. The only supported kind and payment model are `business` and
`b2b_contract`.

For a maintenance change, first verify the source episode and commercial
attribution, then prepare the exact registry entry while preserving other
entries. Review any existing individual ownership or payment history separately;
do not clear it just to make registration pass. After applying the maintenance
change, check Raw's business name and country before requesting processing.
Camera assignment and automatic owner filling skip registered recordings, and
direct individual assignment is refused.

## Processing and import contract

Claims include the confirmed `counterparty`. The worker must preserve that object
and its lowercase `country` in the top-level Clean manifest. Every decoded source
in a batch must have the same registered counterparty. Missing declarations,
unregistered sources, mixed businesses/individuals, or a different country fail
import.

Business source keys must have one of these exact layouts in `6thsense-raw`:

```text
sessions/<confirmed-session>/<full-recording>/<file>
sessions/<confirmed-session>/<uploading-camera>/<full-recording>/<file>
```

The optional uploading-camera folder is six hexadecimal characters, optionally
prefixed by `EGO-`. It may differ from the capture camera after a card swap.
The recording identity, manifest device and calibration still bind the capture
camera; the registry binds the session. Full recording-directory matching,
version/hash checks, artifact requirements and duplicate-source guards remain
in effect.

Imported business runs have `wearer_id: null`, `rate_krw_hour: null` and no KRW
estimate. Worker completion checks the counterparty again and refuses business
runs with an individual owner or rate. A successful completion still requires
exact source receipt reconciliation before Raw is cleared.

## Browsing and review

Raw shows the business name, a **B2B** badge and its registered country, and offers
businesses in the **Raw source** filter. Registered business footage is not
counted as an unassigned individual source.

Clean groups business runs by business ID within their region, separately from
individual contributors. **Filter footage by source** supports both kinds;
region totals include every source and count businesses separately. An explicit
country can resolve a `Trial` session label, while conflicting country evidence
still stays under **Needs region review**.

Quality review remains available, including **Hold for review** with a reason.
For trustworthy NTP capture timestamps, collection dates use the source country's
timezone: Shanghai, Seoul, Ho Chi Minh City or Kolkata. The review form labels
the country and rejects future dates in that timezone; unreliable capture times
still need operator confirmation.

Business ledger entries use payment status `b2b_contract` and no allocated KRW.
They are excluded from individual contributor totals, payout eligibility and
payment approval. Reviewing footage does not settle the business contract or
create a payment. See [Clean browsing](OPS-CLEAN.md) and the
[Ops workflow](OPS-WORKFLOW.md) for the shared playback and review behavior.

## Deployment checkpoint

Version `0.0.8.0` code `7831807` is deployed to Railway: API
`2cf021d6-d0d6-4025-a91b-1d8c0a8823c9` and frontend
`861ab230-4e62-4d17-9c6e-1fe642a8638f` both succeeded. All live API source
hashes match the release; the public frontend serves the business-source
labels, source filter and review controls. API health passes, and the two
existing paid Clean runs retain their original accepted time. Validation passed
210 backend Ops tests, 10 frontend unit tests, the production build and 24
responsive browser tests. Deployment verification does not establish that a
particular media conversion or Raw cleanup has finished.
