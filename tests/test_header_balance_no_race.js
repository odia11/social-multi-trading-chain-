/* The shared topbar's #pt-nb-sol-balance chip shows the total multi-chain
   portfolio value (header-stable-balance.js, dollar-formatted), not a raw
   SOL amount. navbar.js used to ALSO write a raw, unformatted SOL number
   into the same element from its own /api/me fetch -- two systems racing
   to write different-shaped values into one node, on every page, with
   whichever resolved last winning. Combined with the "SOL" unit label
   sitting unhidden next to it on desktop, the chip could end up literally
   reading "$20.95 SOL". */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const css=fs.readFileSync('static/navbar.css','utf8');
const js=fs.readFileSync('static/navbar.js','utf8');
const py=fs.readFileSync('dashboard.py','utf8');

assert(
  !/getElementById\('pt-nb-sol-balance'\)[^;]*textContent\s*=\s*Number\(d\.balance/.test(js),
  'navbar.js must not write a raw SOL number into the shared #pt-nb-sol-balance chip -- ' +
  'header-stable-balance.js is the only thing that writes it, in dollars'
);
assert(js.includes("getElementById('pt-nb-avatar')"), 'the same /api/me fetch must still update the avatar');
assert(js.includes('d.is_admin'), 'the same /api/me fetch must still reveal admin-only nav links');

// The unit label must be hidden unconditionally, not only inside a mobile
// media query -- the chip is a dollar total everywhere, not just on phones.
// This file's own convention is what tells them apart: a rule nested inside
// an @media block is indented, a top-level rule starts at column 0.
assert(/^\.pt-nb-sol-unit\s*\{[^}]*display:\s*none/m.test(css),
  '.pt-nb-sol-unit must be hidden by an UNINDENTED (top-level, not media-query-scoped) rule');

assert(py.includes('id="pt-nb-sol-balance">$0.00<'),
  "the server-rendered placeholder must already be dollar-shaped ('$0.00'), matching what " +
  'header-stable-balance.js replaces it with, so nothing flashes an unformatted number first');

console.log('PASS shared header balance chip: single writer (header-stable-balance.js), dollar-shaped everywhere, no raw-SOL/dollar race');
