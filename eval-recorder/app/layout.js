import './globals.css';

export const metadata = {
  title: 'Urdu Voice Recorder',
  description: 'Record a few Urdu sentences to help evaluate a speech project.',
};

export const viewport = { width: 'device-width', initialScale: 1 };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href="https://fonts.googleapis.com/css2?family=Noto+Nastaliq+Urdu&display=swap" rel="stylesheet" />
      </head>
      <body>{children}</body>
    </html>
  );
}
