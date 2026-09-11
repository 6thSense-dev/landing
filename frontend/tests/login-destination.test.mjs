import test from 'node:test';import assert from 'node:assert/strict';
import {loginDestination} from '../src/portal/roleHome.js';
const owner={role:'admin',workspace_enabled:true};
test('owner default and old leads return migrate to workspace',()=>{for(const next of [null,'/portal/admin','/portal/admin/','/portal/admin?old=true'])assert.equal(loginDestination(next,owner),'/portal/workspace')});
test('intentional safe deep links survive',()=>{for(const next of ['/portal/catalog?clip=one','/portal/ops','/portal/workspace/learn/guest','/portal/intake-review'])assert.equal(loginDestination(next,owner),next)});
test('other accounts retain role homes and cannot use workspace return',()=>{for(const role of ['guest','ops','admin','founder','customer','investor'])assert.equal(loginDestination('/portal/workspace',{role}),role==='guest'?'/portal/catalog':'/portal/'+role);assert.equal(loginDestination('/portal/admin',{role:'admin'}),'/portal/admin')});
test('external or malformed return targets refused',()=>{for(const next of ['https://evil.test/portal/admin','//evil.test/portal/workspace','javascript:alert(1)','/portal/workspace-evil','/portal/admin\n'])assert.equal(loginDestination(next,owner),'/portal/workspace')});
