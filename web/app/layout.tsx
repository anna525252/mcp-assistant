import type { Metadata } from "next";
import { Montserrat } from "next/font/google";
import Header from "./components/header";
import Footer from "./components/footer";
import "./globals.css";

const montserrat = Montserrat({
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700"]
});

export const metadata: Metadata = {
  title: "Tour Agency",
  description: "Бронирование турбаз и домиков с ассистентом",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ru">
      <body className={montserrat.className}>
        <Header />
        <main>{children}</main>
        <Footer />
      </body>
    </html>
  );
}
