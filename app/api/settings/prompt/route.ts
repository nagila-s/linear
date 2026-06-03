import { promises as fs } from "node:fs";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";

const localPromptPath = path.join(process.cwd(), "prompt.txt");

export async function GET(): Promise<NextResponse> {
  try {
    const prompt = await fs.readFile(localPromptPath, "utf-8");
    return NextResponse.json({ prompt });
  } catch {
    return NextResponse.json({ prompt: "" });
  }
}

export async function PUT(request: NextRequest): Promise<NextResponse> {
  const body = (await request.json()) as { prompt?: string };
  const prompt = String(body.prompt ?? "");
  await fs.writeFile(localPromptPath, prompt, "utf-8");
  return NextResponse.json({ prompt });
}
