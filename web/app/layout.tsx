import { AntdRegistry } from "@ant-design/nextjs-registry";
import type { Metadata, Viewport } from "next";
import { Be_Vietnam_Pro, JetBrains_Mono, Noto_Serif } from "next/font/google";
import { AppShell } from "@/components/AppShell";
import { StudioProvider } from "@/components/providers/StudioProvider";
import { ThemeProvider } from "@/components/providers/ThemeProvider";
import { THEME_INIT_SCRIPT } from "@/lib/theme";
import "./globals.css";

const sans = Be_Vietnam_Pro({ subsets: ["latin", "vietnamese"], weight: ["400", "500", "600", "700"], variable: "--font-sans", display: "swap" });
const serif = Noto_Serif({ subsets: ["latin", "vietnamese"], weight: ["600", "700"], variable: "--font-serif", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin", "vietnamese"], weight: ["400", "500"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Emvoox Studio",
  description: "Emvoox: Emotion + Voice. AI audio micro-drama studio with a 7-agent production pipeline.",
  icons: { icon: "/favicon.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0e1522" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${sans.variable} ${serif.variable} ${mono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <AntdRegistry>
          <ThemeProvider>
            <StudioProvider>
              <AppShell>{children}</AppShell>
            </StudioProvider>
          </ThemeProvider>
        </AntdRegistry>
      </body>
    </html>
  );
}
