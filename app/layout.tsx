import type { Metadata } from "next";
import "./globals.css";

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL?.trim() ||
  process.env.VERCEL_URL?.trim() ||
  "https://linear-fdnc.vercel.app";

export const metadata: Metadata = {
  title: "Linear",
  description: "Linearização de livros PDF para a Plataforma Braille.",
  metadataBase: new URL(siteUrl.startsWith("http") ? siteUrl : `https://${siteUrl}`),
  openGraph: {
    title: "Linear",
    description: "Linearização de livros PDF para a Plataforma Braille.",
    type: "website",
    locale: "pt_BR",
    siteName: "Linear",
  },
  twitter: {
    card: "summary_large_image",
    title: "Linear",
    description: "Linearização de livros PDF para a Plataforma Braille.",
  },
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
