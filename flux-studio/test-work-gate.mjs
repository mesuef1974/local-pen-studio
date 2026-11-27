import test from 'node:test';
import assert from 'node:assert/strict';
import {createWorkGate} from './work-gate.js';

function gateWith(){const calls=[];return {calls,gate:createWorkGate({load:file=>calls.push(['load',file]),runStage:step=>calls.push(['run',step]),canRun:step=>step!==1,isAuto:step=>step!==0})};}

test('a queued file is imported first and the queued stage keeps waiting',()=>{
 const {calls,gate}=gateWith();gate.queuedFile='f';gate.pendingStage=2;gate.drain();
 assert.deepEqual(calls,[['load','f']]);assert.equal(gate.queuedFile,null);assert.equal(gate.pendingStage,2);
});

test('a queued stage runs only when it is automatic and runnable',()=>{
 const {calls,gate}=gateWith();for(const step of [0,1,2]){gate.pendingStage=step;gate.drain();assert.equal(gate.pendingStage,null);}
 assert.deepEqual(calls,[['run',2]]);
});

test('draining the file alone reports whether one was waiting',()=>{
 const {calls,gate}=gateWith();gate.pendingStage=2;assert.equal(gate.drainFile(),false);gate.queuedFile='f';assert.equal(gate.drainFile(),true);
 assert.deepEqual(calls,[['load','f']]);
});
