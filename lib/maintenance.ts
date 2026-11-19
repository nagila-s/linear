/**
 * Modo manutenção da plataforma.
 *
 * Com MAINTENANCE_MODE ligado nas variáveis de ambiente da Vercel (1, true, on, sim), o
 * middleware responde 503 para TODAS as rotas que passam por ele, inclusive /login e /api:
 * ninguém entra, nem com a senha. Arquivos estáticos (nome com ponto) não passam pelo
 * middleware e não trazem dados.
 *
 * Ligar: criar MAINTENANCE_MODE=1 em Settings → Environment Variables (Production) e publicar
 * de novo. Desligar: apagar a variável (ou pôr 0) e publicar de novo.
 */

const LIGADO = new Set(["1", "true", "on", "sim", "yes"]);

export function isMaintenanceMode(value: string | undefined = process.env.MAINTENANCE_MODE): boolean {
  return LIGADO.has((value ?? "").trim().toLowerCase());
}

export const MAINTENANCE_HEADERS: Record<string, string> = {
  "Retry-After": "3600",
  "Cache-Control": "no-store",
  "X-Robots-Tag": "noindex, nofollow",
};

export const MAINTENANCE_JSON = {
  error: "Estamos em manutenção. O Linear está temporariamente indisponível para melhorias de segurança. Voltaremos em breve.",
};

export const MAINTENANCE_HTML = `<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Linear em manutenção</title>
<style>
  :root { color-scheme: light dark; --bg: #ffffff; --fg: #1a1a1a; }
  @media (prefers-color-scheme: dark) { :root { --bg: #14171d; --fg: #e8ebf1; } }
  html, body { height: 100%; margin: 0; }
  body { display: grid; place-items: center; background: var(--bg); color: var(--fg);
         font: 1.25rem/1.6 Arial, Helvetica, sans-serif; padding: 0 16px; }
  main { max-width: 44rem; text-align: center; }
  h1 { font-size: 2.25rem; line-height: 1.2; margin: 0 0 1.25rem; }
  p { margin: 0 0 1rem; }
</style>
</head>
<body>
<main>
  <h1>Estamos em manutenção</h1>
  <p>O Linear está temporariamente indisponível para melhorias de segurança.</p>
  <p>Voltaremos em breve. Agradecemos a compreensão.</p>
  <p>Fundação Dorina Nowill para Cegos</p>
</main>
</body>
</html>`;
