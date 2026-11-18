const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function main() {
  const handlers = {};
  const deleted = [];
  const current = "atd-offline-v18";
  const caches = {
    keys: async () => ["atd-offline-v16", current, "atd-offline-v17", "other", "other-atd-offline-v17"],
    delete: async name => deleted.push(name),
  };
  const self = {
    addEventListener: (name, handler) => { handlers[name] = handler; },
    clients: {
      claim() {
        assert.deepEqual(deleted, ["atd-offline-v16", "atd-offline-v17"]);
      },
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../sw.js"), "utf8"), { self, caches });
  let activation;
  handlers.activate({ waitUntil(promise) { activation = promise; } });
  assert.ok(activation);
  await activation;
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
