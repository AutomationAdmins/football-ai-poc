import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Football Editorial Dashboard',
  description: 'Production-ready live football insights dashboard',
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
