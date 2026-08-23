#!/usr/bin/env bash
#
# Provision the private S3 bucket that backs the buyer-facing data catalog.
#
# The catalog never serves media bytes through the API. The API checks the
# caller's role and hands back a short-lived S3 presigned URL; the browser
# fetches the mp4 straight from S3, which gives us HTTP Range (video seeking)
# for free and keeps Railway out of the data path.
#
# Run this ONCE, with credentials that can create buckets and IAM users --
# i.e. NOT the alex-publisher key, which is scoped to the firmware bucket.
#
#   AWS_PROFILE=6thsense-admin ./scripts/catalog/provision_s3.sh
#
# It is idempotent: re-running against an existing bucket only re-applies the
# policy, CORS and lifecycle rules.

set -euo pipefail

BUCKET="${CATALOG_BUCKET:-6thsense-catalog-media}"
REGION="${CATALOG_REGION:-us-west-2}"
# Two identities, deliberately. The writer is used by upload_bundle.py from a
# workstation or CI; the reader is the ONLY one whose key goes into Railway.
# The API never writes -- it calls get_object and generate_presigned_url
# ('get_object', ...) and nothing else (backend/app/core/catalog_store.py) --
# so giving the public web app PutObject/DeleteObject on the whole catalog
# bucket would be handing a delete-and-overwrite primitive to whoever gets the
# environment.
IAM_USER="${CATALOG_IAM_USER:-catalog-media}"                 # read + write (uploads)
IAM_READER="${CATALOG_IAM_READER:-catalog-media-reader}"      # read only  (the API)
# Browser origins allowed to fetch presigned media. Presigned URLs are
# same-origin-agnostic, but <video> with crossorigin and range requests still
# need CORS to be permissive about the Range/ETag headers.
ORIGINS='["https://6thsense.dev","https://www.6thsense.dev","http://localhost:5173","http://localhost:4173"]'

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }

say "Bucket   : s3://${BUCKET}  (${REGION})"
say "IAM user : ${IAM_USER}"
say "Caller   : $(aws sts get-caller-identity --query Arn --output text)"
echo

# ---------------------------------------------------------------- bucket ----
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  say "bucket already exists — reapplying configuration"
else
  say "creating bucket"
  # us-east-1 is the one region that rejects a LocationConstraint.
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
fi

say "blocking all public access (presigned URLs are the only way in)"
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'

say "enabling default encryption"
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

say "enabling versioning (an accidental re-upload should not destroy a delivered clip)"
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration 'Status=Enabled'

say "applying CORS"
aws s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration "$(cat <<JSON
{
  "CORSRules": [
    {
      "AllowedOrigins": ${ORIGINS},
      "AllowedMethods": ["GET", "HEAD"],
      "AllowedHeaders": ["Range", "If-None-Match", "If-Modified-Since"],
      "ExposeHeaders": ["Content-Range", "Content-Length", "Accept-Ranges", "ETag"],
      "MaxAgeSeconds": 3000
    }
  ]
}
JSON
)"

say "expiring noncurrent versions after 30 days"
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" \
  --lifecycle-configuration "$(cat <<'JSON'
{
  "Rules": [
    {
      "ID": "expire-noncurrent",
      "Status": "Enabled",
      "Filter": {"Prefix": ""},
      "NoncurrentVersionExpiration": {"NoncurrentDays": 30},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    }
  ]
}
JSON
)"

# ------------------------------------------------------------------- IAM ----
# Writer: upload_bundle.py, run from a workstation or CI. Never in Railway.
POLICY_NAME="catalog-media-rw"
POLICY_DOC=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListTheBucketOnly",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::${BUCKET}"
    },
    {
      "Sid": "ReadWriteObjects",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
      "Resource": "arn:aws:s3:::${BUCKET}/*"
    }
  ]
}
JSON
)

# Reader: the API. GetObject only -- enough to presign a GET, and nothing else.
READER_POLICY_NAME="catalog-media-ro"
READER_POLICY_DOC=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LocateTheBucket",
      "Effect": "Allow",
      "Action": ["s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::${BUCKET}"
    },
    {
      "Sid": "ReadObjectsOnly",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::${BUCKET}/*"
    }
  ]
}
JSON
)

ensure_user() {
  local user="$1"
  if aws iam get-user --user-name "$user" >/dev/null 2>&1; then
    say "IAM user ${user} already exists"
  else
    say "creating IAM user ${user}"
    aws iam create-user --user-name "$user" >/dev/null
  fi
}

ensure_user "$IAM_USER"
ensure_user "$IAM_READER"

say "attaching inline policy ${POLICY_NAME} to ${IAM_USER} (read+write, this bucket only)"
aws iam put-user-policy --user-name "$IAM_USER" \
  --policy-name "$POLICY_NAME" --policy-document "$POLICY_DOC"

say "attaching inline policy ${READER_POLICY_NAME} to ${IAM_READER} (GetObject only)"
aws iam put-user-policy --user-name "$IAM_READER" \
  --policy-name "$READER_POLICY_NAME" --policy-document "$READER_POLICY_DOC"

# If a previous run of this script put a read/write policy on the reader, or an
# earlier deployment reused the writer for the API, drop the stale grant rather
# than leaving it attached and unmentioned.
if aws iam get-user-policy --user-name "$IAM_READER" --policy-name "$POLICY_NAME" >/dev/null 2>&1; then
  say "removing stale ${POLICY_NAME} from ${IAM_READER}"
  aws iam delete-user-policy --user-name "$IAM_READER" --policy-name "$POLICY_NAME"
fi

echo
say "Bucket ready. Mint the READER key for Railway:"
cat <<EOF

    aws iam create-access-key --user-name ${IAM_READER}

Set these on the Railway backend service (and your local .env). The key below is
the read-only one -- the API never writes, so it must never hold a key that can:

    CATALOG_S3_BUCKET=${BUCKET}
    CATALOG_S3_REGION=${REGION}
    CATALOG_S3_PREFIX=v1/
    CATALOG_AWS_ACCESS_KEY_ID=<AccessKeyId for ${IAM_READER}>
    CATALOG_AWS_SECRET_ACCESS_KEY=<SecretAccessKey for ${IAM_READER}>
    CATALOG_PRESIGN_TTL=900

Uploads use the SEPARATE writer identity, from a workstation or CI only:

    aws iam create-access-key --user-name ${IAM_USER}   # -> an AWS_PROFILE, not Railway
    AWS_PROFILE=catalog-upload \\
      python3 scripts/catalog/upload_bundle.py --bundle <dir> --prefix v1/

EOF
