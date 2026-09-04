"use client";

import { FormEvent, useState } from "react";

import type { ProjectMember } from "@/lib/types";

type Role = ProjectMember["role"];

const roleLabels: Record<Role, string> = {
  admin: "ผู้ดูแลโครงการ",
  sub_admin: "ผู้ช่วยดูแล Progress",
  reviewer: "ผู้ตรวจ Progress",
  viewer: "ดูข้อมูลอย่างเดียว",
};

export function ProjectMembersManager({
  projectId,
  initialMembers,
  currentUserId,
  canManage,
}: {
  projectId: string;
  initialMembers: ProjectMember[];
  currentUserId: string;
  canManage: boolean;
}) {
  const [members, setMembers] = useState(initialMembers);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("reviewer");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function readResponse(response: Response) {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail ?? "ดำเนินการไม่สำเร็จ");
    return body;
  }

  async function addMember(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const member = await readResponse(await fetch(`/api/projects/${projectId}/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, role }),
      })) as ProjectMember;
      setMembers((current) => [...current, member]);
      setEmail("");
      setMessage("เพิ่มสมาชิกเรียบร้อยแล้ว");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "เพิ่มสมาชิกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  async function updateRole(memberId: string, nextRole: Role) {
    setBusy(true);
    setMessage("");
    try {
      const updated = await readResponse(await fetch(`/api/projects/${projectId}/members/${memberId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: nextRole }),
      })) as ProjectMember;
      setMembers((current) => current.map((member) => member.id === memberId ? updated : member));
      setMessage("เปลี่ยนสิทธิ์เรียบร้อยแล้ว");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "เปลี่ยนสิทธิ์ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(member: ProjectMember) {
    if (!window.confirm(`นำ ${member.display_name} ออกจากโครงการหรือไม่`)) return;
    setBusy(true);
    setMessage("");
    try {
      await readResponse(await fetch(`/api/projects/${projectId}/members/${member.id}`, { method: "DELETE" }));
      setMembers((current) => current.filter((item) => item.id !== member.id));
      setMessage("นำสมาชิกออกแล้ว");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "นำสมาชิกออกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="members-manager">
      {canManage && (
        <form className="panel member-invite" onSubmit={addMember}>
          <div>
            <h2>เพิ่มเพื่อนเข้าตรวจงาน</h2>
            <p>ให้เพื่อนสมัครบัญชีก่อน แล้วกรอกอีเมลที่ใช้สมัคร</p>
          </div>
          <label>
            อีเมล
            <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="friend@example.com" />
          </label>
          <label>
            สิทธิ์
            <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
              <option value="reviewer">ผู้ตรวจ Progress</option>
              <option value="sub_admin">Sub Admin · แก้ความยาวและพื้นที่</option>
              <option value="viewer">ดูข้อมูลอย่างเดียว</option>
              <option value="admin">ผู้ดูแลโครงการ</option>
            </select>
          </label>
          <button className="button button-primary" disabled={busy} type="submit">เพิ่มสมาชิก</button>
        </form>
      )}

      {message && <p className="member-message">{message}</p>}

      <section className="panel member-list">
        <header><h2>สมาชิกโครงการ</h2><span>{members.length} คน</span></header>
        {members.map((member) => (
          <div className="member-row" key={member.id}>
            <span className="member-avatar">{member.display_name.trim().slice(0, 1).toUpperCase()}</span>
            <div><strong>{member.display_name}{member.user_id === currentUserId ? " (คุณ)" : ""}</strong><small>{member.email}</small></div>
            {canManage ? (
              <select disabled={busy} value={member.role} onChange={(event) => updateRole(member.id, event.target.value as Role)}>
                <option value="admin">ผู้ดูแลโครงการ</option>
                <option value="sub_admin">Sub Admin · แก้ความยาวและพื้นที่</option>
                <option value="reviewer">ผู้ตรวจ Progress</option>
                <option value="viewer">ดูข้อมูลอย่างเดียว</option>
              </select>
            ) : <span className="member-role">{roleLabels[member.role]}</span>}
            {canManage && member.user_id !== currentUserId
              ? <button className="button button-danger" disabled={busy} onClick={() => removeMember(member)} type="button">นำออก</button>
              : <span />}
          </div>
        ))}
      </section>
    </div>
  );
}
