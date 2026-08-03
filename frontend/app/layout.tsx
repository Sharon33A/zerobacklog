import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ZeroBacklog — Stop Saving. Start Learning.",
  description:
    "Turn postponed learning resources into one clear, personalized action pack.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
