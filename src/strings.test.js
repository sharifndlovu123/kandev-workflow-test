const assert = require('node:assert');
const { test } = require('node:test');
const { reverse, capitalize } = require('./strings');

test('reverse', () => {
  assert.strictEqual(reverse('abc'), 'cba');
});

test('capitalize', () => {
  assert.strictEqual(capitalize('hello'), 'Hello');
  assert.strictEqual(capitalize('hELLO'), 'HELLO');
  assert.strictEqual(capitalize(''), '');
  assert.strictEqual(capitalize('123abc'), '123abc');
  assert.strictEqual(capitalize('a'), 'A');
});
