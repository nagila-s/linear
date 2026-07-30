import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  PromptRouter,
  sanitizePromptOverrides,
  CONTENT_PAGE_TYPE,
} from "./prompt-router";
import { hashPromptSnapshot, validateLinearizationRoot } from "./prompt-hash";
import { createSignedSessionToken, verifySignedSessionToken } from "./session";

describe("sanitizePromptOverrides", () => {
  it("mantem apenas arquivos conhecidos", () => {
    const cleaned = sanitizePromptOverrides({
      "base.txt": "hello",
      "evil.txt": "nope",
      classificador: 123,
      "classificador.txt": "cls",
    });
    assert.deepEqual(cleaned, { "base.txt": "hello", "classificador.txt": "cls" });
  });
});

describe("PromptRouter", () => {
  it("usa snapshot e falha se prompt ausente", () => {
    const router = new PromptRouter({
      "base.txt": "BASE {{SHARED_RULES}}",
      "_shared_rules.txt": "SHARED",
      "classificador.txt": "CLS",
    });
    const { prompt, promptFile } = router.getPrompt("conteudo");
    assert.equal(promptFile, "base.txt");
    assert.equal(prompt, "BASE SHARED");
    assert.equal(router.classifierPrompt, "CLS");
    assert.throws(() => new PromptRouter({}).getPrompt("conteudo"));
  });

  it("respeita miolo_only e janela de classificacao", () => {
    const router = new PromptRouter({ "base.txt": "x", "classificador.txt": "y" });
    assert.equal(router.resolvePageType(1, 100, "capa", true), CONTENT_PAGE_TYPE);
    assert.equal(router.resolvePageType(50, 100, "capa", false), CONTENT_PAGE_TYPE);
    assert.equal(router.resolvePageType(1, 100, "capa", false), "capa");
    assert.equal(PromptRouter.shouldSkipFigurePipeline("capa"), true);
    assert.equal(PromptRouter.shouldSkipFigurePipeline("conteudo"), false);
  });
});

describe("prompt hash + schema", () => {
  it("gera hash estavel e valida raiz", () => {
    const a = hashPromptSnapshot({ "base.txt": "abc", "classificador.txt": "z" });
    const b = hashPromptSnapshot({ "classificador.txt": "z", "base.txt": "abc" });
    assert.equal(a.globalHash, b.globalHash);
    assert.equal(a.hashes["base.txt"]?.length, 64);

    assert.equal(validateLinearizationRoot({ tipo_pagina: "conteudo", pagina: 1, conteudo: [] }).ok, true);
    assert.equal(validateLinearizationRoot({ tipo_pagina: "conteudo", pagina: 1 }).ok, false);
    assert.equal(
      validateLinearizationRoot({
        tipo_pagina: "conteudo",
        pagina: 1,
        conteudo: [],
        idioma_principal: "pt",
      }).ok,
      true,
    );
  });
});

describe("sessao assinada", () => {
  it("cria e valida token", async () => {
    process.env.SESSION_SECRET = "test-secret-for-unit";
    const token = await createSignedSessionToken("u1");
    const payload = await verifySignedSessionToken(token);
    assert.ok(payload);
    assert.equal(payload?.sub, "u1");
    assert.equal(await verifySignedSessionToken("invalid"), null);
    assert.equal(await verifySignedSessionToken(token.slice(0, 10) + "x" + token.slice(11)), null);
  });
});
