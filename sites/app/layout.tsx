import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "ReelDrop | Instagram, Facebook e YouTube",
  description: "Prévia e download de vídeos públicos autorizados em MP4 quando disponíveis na plataforma.",
};
export default function RootLayout({children}:Readonly<{children:React.ReactNode}>) {
  return <html lang="pt-BR"><body>{children}</body></html>;
}
