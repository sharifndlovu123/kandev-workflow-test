const assert = require('node:assert');
const { test } = require('node:test');
const { reverse } = require('./strings');

test('reverse', () => {
  assert.strictEqual(reverse('abc'), 'cba');
});
