import test from 'node:test';
import assert from 'node:assert/strict';
import {needsSignIn} from './session-gate.js';
import {csrfHeader} from './api-client.js';

const reply=(ok,data)=>async()=>({ok,json:async()=>data});

test('only a signed-in account with a permanent password stays in the studio',async()=>{
 assert.equal(await needsSignIn(reply(true,{must_change_password:false})),false);
 assert.equal(await needsSignIn(reply(true,{must_change_password:true})),true);
 assert.equal(await needsSignIn(reply(false,{})),true);
 assert.equal(await needsSignIn(async()=>{throw Error('down');}),true);
});

test('the CSRF header comes from this app’s own cookie only',()=>{
 assert.deepEqual(csrfHeader('csrftoken=other; masar_csrftoken=Ab12'),{'X-CSRFToken':'Ab12'});
 assert.deepEqual(csrfHeader('csrftoken=other'),{});
});
