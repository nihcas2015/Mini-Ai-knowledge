import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Mini AI Knowledge System',
  description: 'Intelligent document-powered Q&A built by Sachin',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-dark-950 text-slate-200 antialiased`}>
        {children}
      </body>
    </html>
  );
}
