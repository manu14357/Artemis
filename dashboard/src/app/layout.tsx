/**
 * Root layout — wraps every page in the ARTEMIS shell.
 * This is a Server Component (no 'use client'), providing the HTML skeleton.
 */
import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'ARTEMIS — Counter-Drone Fusion',
  description: 'Multi-sensor counter-drone fusion dashboard',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
