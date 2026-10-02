import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { classifyFontStyleFromName, transformLooksItalic } from "./font-style";

describe("classifyFontStyleFromName", () => {
  it("reconhece nomes curtos e sufixos de itálico", () => {
    assert.equal(classifyFontStyleFromName("heit"), "italico");
    assert.equal(classifyFontStyleFromName("ABCDEF+MinionStd-It"), "italico");
    assert.equal(classifyFontStyleFromName("Times-Italic"), "italico");
    assert.equal(classifyFontStyleFromName("Helvetica"), "normal");
    assert.equal(classifyFontStyleFromName("Times"), "normal");
    assert.equal(classifyFontStyleFromName("hebo"), "negrito");
    assert.equal(classifyFontStyleFromName("Arial-BoldItalic"), "negrito_italico");
  });

  it("detecta itálico falso pelo cisalhamento do transform", () => {
    assert.equal(transformLooksItalic([12, 0, -3.2, 12, 10, 20]), true);
    assert.equal(transformLooksItalic([12, 0, 0, 12, 10, 20]), false);
    assert.equal(transformLooksItalic([0, 12, -12, 0, 10, 20]), false);
    assert.equal(classifyFontStyleFromName("MinionStd-Regular", [12, 0, -3.2, 12, 40, 80]), "italico");
  });
});
