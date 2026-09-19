import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from app.core.payment_sheet import PaymentSheetClient, PaymentSheetError, clean_values


def test_clean_korean_holder_and_leading_zero_account():
    values,issues=clean_values({'accountHolderName':' 테스트 ', 'bankName':'은행', 'accountNumber':'001-234 567890'})
    assert issues==[] and values['accountNumber']=='001234567890' and values['accountHolderName']=='테스트'
    for number in ('+123456','１２３４５６','1234','123\n456'):
        assert 'accountNumber' in clean_values({'accountHolderName':'A','bankName':'B','accountNumber':number})[1]
    assert 'unsupported_field' in clean_values({'password':'no'})[1]


def test_signed_transport_filters_raw_account_and_hides_provider_errors(monkeypatch):
    monkeypatch.setenv('CONTRIBUTOR_PAYMENT_SHEET_URL','https://script.google.com/macros/s/test/exec')
    monkeypatch.setenv('CONTRIBUTOR_PAYMENT_SHEET_SECRET','test-secret-'*4)
    bank={'contributorId':8,'status':'sheet_saved','submissionId':str(uuid4()),'accountHolderName':'Test','bankLabel':'Bank','maskedAccount':'•••• 7890','submittedAt':'2026-09-19T10:00:00Z','accountNumber':'001234567890'}
    class Response:
        url='https://script.googleusercontent.com/macros/echo'
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,size):return json.dumps({'ok':True,'bank':bank}).encode()
    def transport(request,timeout):
        envelope=json.loads(request.data)
        assert timeout==15
        expected=hmac.new(('test-secret-'*4).encode(),(envelope['timestamp']+'.'+envelope['payload']).encode(),hashlib.sha256).hexdigest()
        assert envelope['signature']==expected
        assert json.loads(envelope['payload'])=={'action':'lookup','contributorId':8}
        return Response()
    monkeypatch.setattr('urllib.request.urlopen',transport)
    receipt=PaymentSheetClient().lookup(8)
    assert 'accountNumber' not in receipt
    bank['contributorId']=9
    with pytest.raises(PaymentSheetError):PaymentSheetClient().lookup(8)
    def failure(*args,**kwargs):raise RuntimeError('private-bank-body')
    monkeypatch.setattr('urllib.request.urlopen',failure)
    with pytest.raises(PaymentSheetError) as error:PaymentSheetClient().lookup(8)
    assert 'private-bank' not in str(error.value)


@pytest.mark.parametrize('url',['http://script.google.com/macros/s/test/exec','https://evil.invalid/macros/s/test/exec','https://script.google.com/macros/s/test/exec?secret=bad'])
def test_endpoint_restriction(monkeypatch,url):
    monkeypatch.setenv('CONTRIBUTOR_PAYMENT_SHEET_URL',url)
    monkeypatch.setenv('CONTRIBUTOR_PAYMENT_SHEET_SECRET','s'*40)
    with pytest.raises(PaymentSheetError):PaymentSheetClient()
