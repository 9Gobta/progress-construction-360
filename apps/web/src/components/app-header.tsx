import Link from "next/link";

import type { User } from "@/lib/types";

export function AppHeader({ user, viewerTitle }: { user: User | null; viewerTitle?: string }) {
  return (
    <header className={`app-header ${viewerTitle ? "viewer-app-header" : ""}`}>
      <div className="header-inner section-wrap">
        <Link aria-label="Progress Construction 360" className="brand" href="/" title="Progress Construction 360">
          <span className="brand-mark">PC</span>
          {!viewerTitle && <span>Progress Construction 360</span>}
        </Link>
        {viewerTitle ? <strong className="viewer-header-title">{viewerTitle}</strong> : <nav className="header-nav" aria-label="เมนูหลัก">
          <Link href="/projects">โครงการ</Link>
          <span>Capture</span>
          <span>ตรวจ Progress</span>
          <span>Dashboard</span>
        </nav>}
        <div className="header-account">
          {user ? (
            <>
              <span className="account-name">{user.display_name}</span>
              <form action="/api/session/logout" method="post">
                <button aria-label="ออกจากระบบ" className={`button button-ghost ${viewerTitle ? "header-icon-button" : ""}`} title="ออกจากระบบ" type="submit">{viewerTitle ? <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M10 5H5v14h5M14 8l4 4-4 4M18 12H9" /></svg> : "ออกจากระบบ"}</button>
              </form>
            </>
          ) : (
            <Link className="button button-ghost" href="/login">เข้าสู่ระบบ</Link>
          )}
        </div>
      </div>
    </header>
  );
}
