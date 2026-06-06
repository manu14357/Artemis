/**
 * Root layout — wraps every page in the ARTEMIS shell.
 * This is a Server Component (no 'use client'), providing the HTML skeleton.
 */
import type { Metadata } from 'next';
import Link from 'next/link';
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
      <body style={{ margin: 0, background: '#0a0f1a', color: '#e2e8f0', fontFamily: 'system-ui, sans-serif' }}>
        {/* ── Global nav bar ── */}
        <nav style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          padding: '0 20px',
          height: 40,
          background: '#060b14',
          borderBottom: '1px solid #1e3a5f',
          position: 'sticky',
          top: 0,
          zIndex: 1000,
        }}>
          <span style={{ fontWeight: 900, fontSize: 14, letterSpacing: 3, color: '#3b82f6', marginRight: 16 }}>
            ARTEMIS
          </span>
          {[
            { href: '/',           label: 'Dashboard'  },
            { href: '/analytics',  label: 'Analytics'  },
            { href: '/scenarios',  label: 'Scenarios'  },
            { href: '/settings',   label: 'Settings'   },
          ].map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              style={{
                padding: '4px 12px',
                borderRadius: 4,
                fontSize: 12,
                fontWeight: 600,
                color: '#94a3b8',
                textDecoration: 'none',
                letterSpacing: 0.5,
              }}
            >
              {label}
            </Link>
          ))}
        </nav>
        {children}
      </body>
    </html>
  );
}
