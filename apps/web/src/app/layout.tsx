import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Progress Construction 360",
    template: "%s · Progress Construction 360",
  },
  description: "ตรวจความก้าวหน้างานก่อสร้างจากวิดีโอ 360 องศาเทียบกับแผนงาน",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="th">
      <body>{children}</body>
    </html>
  );
}
