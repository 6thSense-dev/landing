import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// Execute the real data layer with only Vite's environment expanded. Bundling
// retains React and the real portalFetch, so deferred network responses exercise
// the same cache/promise ownership logic as the browser.
const result = await build({ entryPoints: [new URL("../src/catalog/useCatalog.js", import.meta.url).pathname], bundle:true, platform:"node",format:"esm",write:false,define:{"import.meta.env":"{}"} });
const dir = await mkdtemp(join(tmpdir(),"workspace-cache-"));
const file=join(dir,"module.mjs");await writeFile(file,result.outputFiles[0].text);
const cache=await import(pathToFileURL(file));
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}
const doc = label => ({schema:"6s-catalog/1.0",collection:{id:label},clips:[],expires_at:"2099-01-01T00:00:00Z"});
function response(label){return new Response(JSON.stringify(doc(label)),{status:200,headers:{"Content-Type":"application/json"}});}

test("pending admin to guest starts new fetch and never revives admin data",async()=>{
 const requests=[];globalThis.fetch=(url)=>{const d=deferred();requests.push({url,...d});return d.promise;};
 cache.bindCatalogIdentity("3:admin:admin","/api/workspace/catalog/admin");const old=cache.ensureCatalog();
 cache.bindCatalogIdentity("3:admin:guest","/api/workspace/catalog/guest");const current=cache.ensureCatalog();
 assert.equal(requests.length,2);assert.equal(requests[1].url,"/api/workspace/catalog/guest");
 requests[0].resolve(response("admin"));await old;
 requests[1].resolve(response("guest"));assert.equal((await current).collection.id,"guest");
 assert.equal((await cache.ensureCatalog()).collection.id,"guest");
});

test("A to B to A ignores first A and previous promise failures",async()=>{
 const requests=[];globalThis.fetch=(url)=>{const d=deferred();requests.push({url,...d});return d.promise;};
 cache.bindCatalogIdentity("A","/api/workspace/catalog/admin");const old=cache.ensureCatalog();
 cache.bindCatalogIdentity("B","/api/workspace/catalog/guest");const middle=cache.ensureCatalog().catch(()=>null);
 cache.bindCatalogIdentity("A","/api/workspace/catalog/admin");const fresh=cache.ensureCatalog();
 assert.equal(requests.length,3);
 requests[0].resolve(response("stale-admin"));await old;
 assert.equal(cache.ensureCatalog(),fresh);
 requests[1].resolve(new Response("{}",{status:503}));await middle;
 assert.equal(cache.ensureCatalog(),fresh);
 requests[2].resolve(response("fresh-admin"));await fresh;
 assert.equal((await cache.ensureCatalog()).collection.id,"fresh-admin");
});

test("unscoped work uses its own cache and untrusted paths fail closed",async()=>{
 let url;globalThis.fetch=async u=>{url=u;return response("live");};
 cache.bindCatalogIdentity("live");assert.equal((await cache.ensureCatalog()).collection.id,"live");assert.equal(url,"/api/catalog");
 assert.throws(()=>cache.bindCatalogIdentity("bad","https://evil.test"));
 assert.throws(()=>cache.bindCatalogIdentity("bad","/api/workspace/catalog/ops"));
});

test.after(async()=>{await rm(dir,{recursive:true,force:true});});
