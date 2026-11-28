import test from 'node:test';
import assert from 'node:assert/strict';
import {describe,fileName} from './cut-view.js';

const piece={widthMm:102.9,heightMm:120,holes:47,pieces:1,weakParts:0};

test('a sound piece has no warnings',()=>{
 assert.deepEqual(describe(piece).warnings,[]);
 assert.match(describe(piece).facts,/102\.9×120/);
});

test('loose, weak and small pieces are each reported',()=>{
 assert.equal(describe({...piece,pieces:2,weakParts:1,widthMm:70,heightMm:90}).warnings.length,3);
});

test('file names keep Arabic and drop reserved characters',()=>{
 assert.equal(fileName(' مسك ',true),'مسك-mirrored.svg');
 assert.equal(fileName('a/b:c d',false),'abc-d.svg');
 assert.equal(fileName('..',false),'cut.svg');
});
