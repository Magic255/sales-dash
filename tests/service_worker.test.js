const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const serviceWorkerSource = fs.readFileSync(
  path.join(__dirname, "../frontend/service-worker.js"),
  "utf8"
);

function createHarness({fetchImpl, cachedResponse} = {}) {
  const handlers = {};
  const calls = {
    cacheAdds: [],
    cacheMatches: [],
    cachePuts: [],
    fetches: [],
    deletedCaches: [],
  };
  const cache = {
    addAll: async (assets) => calls.cacheAdds.push(Array.from(assets)),
    put: async (key, response) => calls.cachePuts.push({key, response}),
  };
  const caches = {
    open: async () => cache,
    match: async (request) => {
      calls.cacheMatches.push(request);
      return cachedResponse;
    },
    keys: async () => ["sales-dash-shell-old", "unrelated-cache"],
    delete: async (key) => {
      calls.deletedCaches.push(key);
      return true;
    },
  };
  const networkFetch = fetchImpl || (async (request) => {
    calls.fetches.push(request);
    return {ok: true, clone() { return this; }};
  });
  const self = {
    location: {origin: "https://sales.example.test"},
    clients: {claim: async () => {}},
    addEventListener: (name, handler) => { handlers[name] = handler; },
    skipWaiting: () => {},
  };

  vm.runInNewContext(serviceWorkerSource, {
    self,
    caches,
    fetch: networkFetch,
    URL,
    Promise,
  });

  return {handlers, calls};
}

function dispatchFetch(handlers, request) {
  let responsePromise;
  let intercepted = false;
  handlers.fetch({
    request,
    respondWith(promise) {
      intercepted = true;
      responsePromise = promise;
    },
  });
  return {intercepted, responsePromise};
}

test("install caches only the public app shell", async () => {
  const {handlers, calls} = createHarness();
  let installPromise;
  handlers.install({waitUntil(promise) { installPromise = promise; }});
  await installPromise;

  assert.equal(calls.cacheAdds.length, 1);
  assert.ok(calls.cacheAdds[0].includes("/"));
  assert.ok(calls.cacheAdds[0].includes("/static/auth.js"));
  assert.ok(calls.cacheAdds[0].every((asset) => !asset.startsWith("/api/")));
});

test("private API and non-GET requests are never intercepted by the service worker", () => {
  const {handlers, calls} = createHarness();

  const privateApi = dispatchFetch(handlers, {
    method: "GET",
    url: "https://sales.example.test/api/customers",
  });
  const privateSale = dispatchFetch(handlers, {
    method: "POST",
    url: "https://sales.example.test/api/sales",
  });
  const externalAsset = dispatchFetch(handlers, {
    method: "GET",
    url: "https://cdn.example.test/library.js",
  });

  assert.equal(privateApi.intercepted, false);
  assert.equal(privateSale.intercepted, false);
  assert.equal(externalAsset.intercepted, false);
  assert.equal(calls.cacheMatches.length, 0);
  assert.equal(calls.cachePuts.length, 0);
  assert.equal(calls.fetches.length, 0);
});

test("same-origin public shell assets may use the cache and network fallback", async () => {
  const {handlers, calls} = createHarness();
  const request = {
    method: "GET",
    url: "https://sales.example.test/static/styles.css",
  };
  const result = dispatchFetch(handlers, request);

  assert.equal(result.intercepted, true);
  await result.responsePromise;
  assert.equal(calls.cacheMatches.length, 1);
  assert.equal(calls.fetches.length, 1);
  assert.equal(calls.cachePuts.length, 0);
});

test("offline root navigation falls back to the cached public shell", async () => {
  const offlineShell = {offline: true};
  const {handlers} = createHarness({
    fetchImpl: async () => { throw new Error("offline"); },
    cachedResponse: offlineShell,
  });
  const result = dispatchFetch(handlers, {
    method: "GET",
    url: "https://sales.example.test/",
  });

  assert.equal(result.intercepted, true);
  assert.equal(await result.responsePromise, offlineShell);
});
