import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Linear",
  description: "Linear - Processamento de livros PDF",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
