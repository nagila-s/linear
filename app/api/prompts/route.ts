import { readdir, readFile } from "fs/promises";
import path from "path";
import { NextResponse } from "next/server";

const PROMPTS_DIR = path.join(process.cwd(), "prompts");

export type PromptFile = {
  name: string;
  content: string;
};

export async function GET(): Promise<NextResponse> {
  try {
    const entries = await readdir(PROMPTS_DIR, { withFileTypes: true });
    const files: PromptFile[] = [];

    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith(".txt")) continue;
      const content = await readFile(path.join(PROMPTS_DIR, entry.name), "utf-8");
      files.push({ name: entry.name, content });
    }

    files.sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));

    return NextResponse.json({ prompts: files });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Falha ao listar prompts do sistema.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
