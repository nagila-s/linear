"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setClientSessionToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
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
            const response = await fetch("/api/auth/login", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ password }),
            });
            const payload = (await response.json()) as { token?: string; error?: string };
            setLoading(false);
            if (!response.ok || !payload.token) {
              setError(payload.error ?? "Falha ao autenticar.");
              return;
            }
            setClientSessionToken(payload.token);
            router.push("/");
          }}
        >
          <input
            type="password"
            placeholder="Senha"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:border-zinc-500"
            required
          />
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
