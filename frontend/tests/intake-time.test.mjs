import assert from 'node:assert/strict';
import { test } from 'node:test';
import { secondsFromNs, nsFromSeconds } from '../src/portal/intakeTime.js';
test('exact nanoseconds above JS safe integer and negative relative time', () => {
  const origin = '9007199254741092';
  for (const seconds of ['0', '0.000000001', '0.3', '-0.000000001', '123456789.123456789']) {
    assert.equal(secondsFromNs(nsFromSeconds(seconds,origin),origin),seconds);
  }
});
test('reject ambiguous or lossy decimal text', () => {
  for (const text of ['1e3','NaN','Infinity','0.0000000001','01',' 1','1.']) assert.throws(() => nsFromSeconds(text,'0'));
});
