"""Built existing portal UI, synthetic HTTP transport; backend RBAC tested separately."""
import json, sys
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core.ops_intake_preview import project_preview
fixture=Path(__file__).parent/'fixtures/intake/synthetic.json'
preview=project_preview(json.loads(fixture.read_text()),now=datetime(2026,9,10,12,tzinfo=timezone.utc))
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1500,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def api(route):
        path=route.request.url.split('/api/')[-1]
        data=({'id':1,'name':'Synthetic Ops','email':'ops@example.test','role':'ops','is_active':True} if path=='auth/me' else {'rate_krw':999,'episodes':[],'wearers':[],'tasks':[],'last_scan':None} if path=='ops/state' else preview)
        route.fulfill(json=data)
    page.route('**/api/**',api)
    page.goto('http://127.0.0.1:4187/portal/ops')
    panel=page.locator('.ops-intake')
    expect(panel).to_contain_text('100 KRW');expect(panel).to_contain_text('rejected');expect(panel).to_contain_text('40 KRW');expect(panel).to_contain_text('SYNTHETIC')
    page.screenshot(path='/tmp/ops-intake-preview-review.png',full_page=True)
    huge=2**100+123
    preview['rows'][0]['credit_minor']=str(huge)
    preview['rows'][0]['judgments']['annotation']['reason']='<img src=x onerror=alert(1)>'
    page.get_by_role('button',name='Reload evidence').click()
    expect(panel).to_contain_text(f'{huge:,} KRW');expect(panel).to_contain_text('<img src=x onerror=alert(1)>');assert panel.locator('img').count()==0
    preview['valid_for_ms']=100
    page.get_by_role('button',name='Reload evidence').click()
    expect(panel).to_contain_text('Snapshot expired');expect(panel).not_to_contain_text(f'{huge:,} KRW')
    preview['valid_for_ms']=60000
    preview['rows'][0].update(credit_minor=None,observed_settled_minor=None,settled_minor=None,outstanding_minor=None,
                              legacy_amount_minor=None,legacy_paid=None,correction_count=None,source_binding='conflict')
    page.get_by_role('button',name='Reload evidence').click()
    expect(panel).to_contain_text('Legacy marked-paid: unknown');expect(panel).to_contain_text('Correction history: unknown')
    expect(panel).not_to_contain_text('null reported assertion corrections')
    preview.update(status='unknown',rows=[],reasons=['snapshot_not_configured'])
    page.get_by_role('button',name='Reload evidence').click()
    expect(panel).to_contain_text('snapshot not configured');assert not errors,errors
    browser.close()
print('Browser checks passed: native projection, separate annotation, exact huge money, escaped HTML, expiry clearing, source-conflict unknowns, unconfigured clearing; no page errors.')
