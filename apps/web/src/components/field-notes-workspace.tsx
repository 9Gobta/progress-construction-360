"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { FieldNoteMarkup } from "@/components/field-note-markup";
import type { FieldNote, FieldNoteStatus, ProjectMember } from "@/lib/types";

const STATUS_LABELS: Record<FieldNoteStatus, string> = {
  OPEN: "เปิดอยู่", P1: "ด่วนมาก P1", P2: "เร่งด่วน P2", P3: "ติดตาม P3",
  COMPLETED: "ดำเนินการแล้ว", VERIFIED: "ตรวจยืนยันแล้ว",
};

function StatusBadge({ status }: { status: FieldNoteStatus }) {
  return <span className={`field-note-status status-${status.toLowerCase()}`}>{STATUS_LABELS[status]}</span>;
}

export function FieldNoteDetail({ note, projectId, members, canEdit, onChange }: {
  note: FieldNote;
  projectId: string;
  members: ProjectMember[];
  canEdit: boolean;
  onChange: (note: FieldNote) => void;
}) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function patch(values: Record<string, unknown>) {
    setBusy(true); setMessage("");
    const response = await fetch(`/api/projects/${projectId}/field-notes/${note.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values),
    });
    const body = await response.json();
    setBusy(false);
    if (!response.ok) return setMessage(body.detail ?? "บันทึกไม่สำเร็จ");
    onChange(body); setMessage("บันทึกแล้ว");
  }

  async function addComment() {
    if (!comment.trim()) return;
    setBusy(true);
    const response = await fetch(`/api/projects/${projectId}/field-notes/${note.id}/comments`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: comment }),
    });
    const body = await response.json(); setBusy(false);
    if (!response.ok) return setMessage(body.detail ?? "เพิ่มความคิดเห็นไม่สำเร็จ");
    setComment(""); onChange(body);
  }

  async function attach(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    const form = new FormData(); form.set("file", file);
    const response = await fetch(`/api/projects/${projectId}/field-notes/${note.id}/attachments`, { method: "POST", body: form });
    const body = await response.json(); setBusy(false);
    if (!response.ok) return setMessage(body.detail ?? "แนบไฟล์ไม่สำเร็จ");
    onChange(body);
  }

  return <div className="field-note-detail">
    <div className="field-note-evidence">
      <Image alt={`หลักฐาน ${note.title}`} fill sizes="(max-width: 800px) 100vw, 560px" src={note.image_url} unoptimized />
      <FieldNoteMarkup canEdit={canEdit} key={`${note.id}:${note.updated_at}`} onSave={(paths) => void patch({ markup_paths: paths })} paths={note.markup_paths ?? []} />
      <Link href={`/projects/${projectId}/captures/${note.capture_id}?keyframe=${note.keyframe_id}`}>
        เปิดตำแหน่งนี้ในภาพ 360
      </Link>
    </div>
    <div className="field-note-fields">
      <header><div><strong>{note.title}</strong><small>{note.floor_name} · {new Date(note.capture_date).toLocaleDateString("th-TH")} · {Math.round(note.keyframe_timestamp_ms / 1000)} วินาที</small></div><StatusBadge status={note.status} /></header>
      <p>{note.description || "ยังไม่มีรายละเอียด"}</p>
      <label><span>สถานะและความสำคัญ</span><select disabled={!canEdit || busy} onChange={(event) => void patch({ status: event.target.value })} value={note.status}>
        {Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label><span>ผู้รับผิดชอบ</span><select disabled={!canEdit || busy} onChange={(event) => void patch({ assignee_id: event.target.value || null })} value={note.assignee_id ?? ""}>
        <option value="">ยังไม่มอบหมาย</option>{members.map((member) => <option key={member.user_id} value={member.user_id}>{member.display_name}</option>)}
      </select></label>
      <label><span>กำหนดส่ง</span><input disabled={!canEdit || busy} onChange={(event) => void patch({ due_date: event.target.value || null })} type="date" value={note.due_date ?? ""} /></label>
      <div className="field-note-tags">{note.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
      <section><strong>ความคิดเห็น ({note.comments.length})</strong>{note.comments.map((item) => <p className="field-note-comment" key={item.id}><b>{item.created_by_name}</b>{item.body}<small>{new Date(item.created_at).toLocaleString("th-TH")}</small></p>)}
        {canEdit && <div className="field-note-comment-form"><input onChange={(event) => setComment(event.target.value)} placeholder="เพิ่มความคิดเห็น" value={comment} /><button disabled={busy || !comment.trim()} onClick={() => void addComment()} type="button">ส่ง</button></div>}
      </section>
      <section><strong>ไฟล์แนบ ({note.attachments.length})</strong><div className="field-note-attachments">{note.attachments.map((item) => <a href={item.download_url} key={item.id} rel="noreferrer" target="_blank">{item.filename}</a>)}</div>
        {canEdit && <label className="field-note-file"><input accept="image/jpeg,image/png,image/webp,application/pdf" disabled={busy} onChange={(event) => void attach(event.target.files?.[0])} type="file" /><span>แนบรูปหรือ PDF</span></label>}
      </section>
      {message && <small role="status">{message}</small>}
    </div>
  </div>;
}

export function FieldNotesWorkspace({ projectId, notes: initialNotes, members, canEdit }: {
  projectId: string;
  notes: FieldNote[];
  members: ProjectMember[];
  canEdit: boolean;
}) {
  const router = useRouter();
  const [notes, setNotes] = useState(initialNotes);
  const [selectedId, setSelectedId] = useState(initialNotes[0]?.id ?? null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("ALL");
  const [floor, setFloor] = useState("ALL");
  const [assignee, setAssignee] = useState("ALL");
  const [tag, setTag] = useState("ALL");
  const [captureDate, setCaptureDate] = useState("ALL");
  const selected = notes.find((item) => item.id === selectedId) ?? null;
  const floors = [...new Map(notes.map((item) => [item.floor_id, item.floor_name])).entries()];
  const tags = [...new Set(notes.flatMap((item) => item.tags))].sort((a, b) => a.localeCompare(b, "th"));
  const dates = [...new Set(notes.map((item) => item.capture_date.slice(0, 10)))].sort().reverse();
  const filtered = useMemo(() => notes.filter((note) => (
    (status === "ALL" || note.status === status)
    && (floor === "ALL" || note.floor_id === floor)
    && (assignee === "ALL" || (assignee === "UNASSIGNED" ? !note.assignee_id : note.assignee_id === assignee))
    && (tag === "ALL" || note.tags.includes(tag))
    && (captureDate === "ALL" || note.capture_date.slice(0, 10) === captureDate)
    && (!query.trim() || `${note.title} ${note.description ?? ""} ${note.tags.join(" ")}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  )), [assignee, captureDate, floor, notes, query, status, tag]);
  function replace(next: FieldNote) {
    setNotes((current) => current.map((item) => item.id === next.id ? next : item));
    router.refresh();
  }

  return <section className="field-notes-page">
    <header className="field-notes-header"><div><span>บันทึกจากหลักฐาน 360</span><h1>ประเด็นหน้างาน</h1><p>ทุกประเด็นผูกกับวัน ชั้น ตำแหน่งบนแปลน และภาพ 360 ที่ตรวจสอบย้อนกลับได้</p></div><button onClick={() => window.print()} type="button">พิมพ์ / บันทึก PDF</button></header>
    <div className="field-notes-layout">
      <aside className="field-notes-list"><div className="field-note-filters"><input onChange={(event) => setQuery(event.target.value)} placeholder="ค้นหาหัวข้อ รายละเอียด หรือแท็ก" value={query} /><select onChange={(event) => setFloor(event.target.value)} value={floor}><option value="ALL">ทุกชั้น</option>{floors.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select><select onChange={(event) => setStatus(event.target.value)} value={status}><option value="ALL">ทุกสถานะ</option>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select onChange={(event) => setCaptureDate(event.target.value)} value={captureDate}><option value="ALL">ทุกวันที่ Capture</option>{dates.map((date) => <option key={date} value={date}>{new Date(`${date}T00:00:00`).toLocaleDateString("th-TH")}</option>)}</select><select onChange={(event) => setAssignee(event.target.value)} value={assignee}><option value="ALL">ผู้รับผิดชอบทั้งหมด</option><option value="UNASSIGNED">ยังไม่มอบหมาย</option>{members.map((member) => <option key={member.user_id} value={member.user_id}>{member.display_name}</option>)}</select><select onChange={(event) => setTag(event.target.value)} value={tag}><option value="ALL">ทุกแท็ก</option>{tags.map((item) => <option key={item} value={item}>{item}</option>)}</select></div>
        <strong>{filtered.length} รายการ</strong>{filtered.map((note) => <button className={note.id === selectedId ? "is-active" : ""} key={note.id} onClick={() => setSelectedId(note.id)} type="button"><span><b>{note.title}</b><small>{note.floor_name} · {new Date(note.capture_date).toLocaleDateString("th-TH")}</small></span><StatusBadge status={note.status} /></button>)}
        {!filtered.length && <p>ไม่พบบันทึกตามตัวกรอง</p>}
      </aside>
      <main>{selected ? <FieldNoteDetail canEdit={canEdit} members={members} note={selected} onChange={replace} projectId={projectId} /> : <div className="field-note-empty">เลือกบันทึกเพื่อดูหลักฐานและรายละเอียด</div>}</main>
    </div>
    <section className="field-notes-print-report">
      <header><span>PROGRESS CONSTRUCTION 360</span><h1>รายงานประเด็นหน้างาน</h1><p>รายงานตามตัวกรองปัจจุบัน · {filtered.length} รายการ</p></header>
      <div className="field-note-report-summary">{Object.entries(STATUS_LABELS).map(([value, label]) => <div key={value}><b>{filtered.filter((note) => note.status === value).length}</b><span>{label}</span></div>)}</div>
      {filtered.map((note, index) => <article key={note.id}><header><b>#{index + 1} {note.title}</b><StatusBadge status={note.status} /></header><div><div className="field-note-report-image"><Image alt={note.title} fill sizes="700px" src={note.image_url} unoptimized /><FieldNoteMarkup canEdit={false} onSave={() => undefined} paths={note.markup_paths ?? []} /></div><dl><dt>วันและเวลา Capture</dt><dd>{new Date(note.capture_date).toLocaleString("th-TH")}</dd><dt>ชั้น / ตำแหน่งภาพ</dt><dd>{note.floor_name} · {Math.round(note.keyframe_timestamp_ms / 1000)} วินาที</dd><dt>ผู้สร้าง</dt><dd>{note.created_by_name}</dd><dt>ผู้รับผิดชอบ</dt><dd>{note.assignee_name || "ยังไม่มอบหมาย"}</dd><dt>กำหนดส่ง</dt><dd>{note.due_date ? new Date(`${note.due_date}T00:00:00`).toLocaleDateString("th-TH") : "ไม่กำหนด"}</dd><dt>แท็ก</dt><dd>{note.tags.join(", ") || "—"}</dd><dt>รายละเอียด</dt><dd>{note.description || "—"}</dd></dl></div></article>)}
    </section>
  </section>;
}
