"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setClientSessionToken } from "@/lib/auth";

async function readLoginResponse(response: Response): Promise<{ token?: string; error?: string }> {
  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();

  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(body) as { token?: string; error?: string };
    } catch {
      return { error: "Resposta invalida do servidor." };
    }
  }

  if (response.status === 404) {
    return { error: "Rota de login nao encontrada. Verifique o deploy na Vercel." };
  }

  if (body.trimStart().startsWith("<")) {
    return {
      error:
        response.status >= 500
          ? "Erro no servidor. Confira ACCESS_PASSWORD nas variaveis da Vercel."
          : "Resposta inesperada do servidor (nao JSON).",
    };
  }

  return { error: body.slice(0, 200) || "Falha ao autenticar." };
}

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  return (
    <main className="flex min-h-screen items-center justify-center bg-white px-4">
      <div className="w-full max-w-sm rounded-xl border border-zinc-200 p-6 shadow-sm">
        <h1 className="text-2xl font-semibold text-zinc-900">Entrar no Linear</h1>
        <p className="mt-2 text-sm text-zinc-600">Informe a senha de acesso.</p>
        <form
          className="mt-5 space-y-4"
          onSubmit={async (event) => {
            event.preventDefault();
            setError("");
            setLoading(true);
            try {
              const response = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password }),
              });
              const payload = await readLoginResponse(response);
              if (!response.ok || !payload.token) {
                setError(payload.error ?? "Falha ao autenticar.");
                return;
              }
              setClientSessionToken(payload.token);
              router.push("/");
              router.refresh();
            } catch {
              setError("Nao foi possivel contactar o servidor. Tente de novo.");
            } finally {
              setLoading(false);
            }
          }}
        >
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              placeholder="Senha"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 pr-24 outline-none focus:border-zinc-500"
              required
              autoComplete="current-password"
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded px-2 py-1 text-xs font-medium text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
              aria-pressed={showPassword}
            >
              {showPassword ? "Ocultar" : "Mostrar"}
            </button>
          </div>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-full bg-zinc-900 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-700 disabled:opacity-60"
          >
            {loading ? "Validando..." : "Entrar"}
          </button>
        </form>
      </div>
    </main>
  );
}
