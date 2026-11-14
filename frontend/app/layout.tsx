import type { Metadata } from "next";
import "./globals.css";
import Header from "./components/Header";
import { SessionProvider } from "./lib/session";

export const metadata: Metadata = {
  title: "TravelHub B2B",
  description: "Agency booking portal (mock target)",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <SessionProvider>
          <Header />
          <main className="mx-auto max-w-6xl px-6 py-10">{children}</main>
        </SessionProvider>
      </body>
    </html>
  );
}
