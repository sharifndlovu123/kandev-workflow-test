// Small utility module — deliberately minimal so agents have something to extend.
function reverse(str) {
  return str.split('').reverse().join('');
}

module.exports = { reverse };
