export default function RootLayout({ children }: { children: React.ReactNode }) {
    return (
      <html lang="en">
        <body style={{ fontFamily: "sans-serif", background: "#fafcff" }}>
          {children}
        </body>
      </html>
    );
  }
  
