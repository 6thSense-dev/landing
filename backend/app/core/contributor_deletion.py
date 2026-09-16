"""One lock orders mobile changes, operator approval, and irreversible erasure.

Provider deletion is idempotent: a missing user is success, all other errors
remain retryable. Never retain tokens or provider error bodies in the audit.
"""
import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import HTTPException
from sqlalchemy import select, text
from app.models.contributor import ContributorAccount, ContributorDeletion

async def lock(db):
    await db.execute(text('SELECT pg_advisory_xact_lock(61306129)'))

async def ensure_active(db, subject):
    await lock(db)
    if await db.get(ContributorDeletion, subject):
        raise HTTPException(403, 'account_deletion_pending')

async def ensure_wearer_active(db, wearer_id):
    await lock(db)
    account = (await db.execute(select(ContributorAccount).where(ContributorAccount.wearer_id == wearer_id))).scalar_one_or_none()
    if account and await db.get(ContributorDeletion, account.subject):
        raise HTTPException(403, 'account_deletion_pending')

def delete_cognito_user(subject):
    pool = os.getenv('CONTRIBUTOR_COGNITO_POOL')
    if not pool:
        raise RuntimeError('Identity deletion is not configured')
    client = boto3.client('cognito-idp', region_name=os.getenv('CONTRIBUTOR_COGNITO_REGION','us-west-2'),
                          config=Config(connect_timeout=4,read_timeout=8,retries={'max_attempts':1}))
    try:
        client.admin_delete_user(UserPoolId=pool, Username=subject)
    except ClientError as error:
        if error.response['Error']['Code'] != 'UserNotFoundException':
            raise

async def pending_wearers(db):
    return set((await db.execute(select(ContributorAccount.wearer_id).join(
        ContributorDeletion, ContributorDeletion.subject == ContributorAccount.subject))).scalars())
