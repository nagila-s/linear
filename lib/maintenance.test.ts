import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { MAINTENANCE_HEADERS, isMaintenanceMode } from "./maintenance";

describe("isMaintenanceMode", () => {
  it("liga com 1, true, on e sim, sem diferenciar maiúsculas e espaços", () => {
    for (const v of ["1", "true", "TRUE", " on ", "sim", "yes"]) assert.equal(isMaintenanceMode(v), true, v);
  });
  it("fica desligado sem a variável ou com 0/false", () => {
    for (const v of [undefined, "", "0", "false", "off", "nao"]) assert.equal(isMaintenanceMode(v), false, String(v));
  });
  it("resposta não fica em cache nem é indexada", () => {
    assert.equal(MAINTENANCE_HEADERS["Cache-Control"], "no-store");
    assert.match(MAINTENANCE_HEADERS["X-Robots-Tag"], /noindex/);
  });
});
