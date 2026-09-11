"use client";

import Link from "next/link";
import Image from "next/image";
import { FormEvent, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { BimModelUploader } from "@/components/bim-model-uploader";
import type { BimModelList, Floor, Project } from "@/lib/types";

type Tab = "details" | "floors" | "bim" | "schedule" | "members";

async function responseBody(response: Response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "ดำเนินการไม่สำเร็จ");
  return body;
}

function FloorPlanRow({ floor, projectId, canEdit }: { floor: Floor; projectId: string; canEdit: boolean }) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setMessage(null);
    try {
      const data = new FormData();
      data.set("file", file);
      await responseBody(await fetch(`/api/projects/${projectId}/floors/${floor.id}/plan`, { method: "POST", body: data }));
      setMessage("อัปโหลดแปลนแล้ว");
      router.refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "อัปโหลดแปลนไม่สำเร็จ"); }
    finally { setBusy(false); if (input.current) input.current.value = ""; }
  }

  return <article className="settings-floor-row"><div className="settings-floor-preview">{floor.has_plan ? <Image alt={`แปลน ${floor.name}`} fill sizes="180px" src={`/api/projects/${projectId}/floors/${floor.id}/plan`} unoptimized /> : <span>ยังไม่มีแปลน</span>}</div><div><strong>{floor.name}</strong><small>ลำดับชั้น {floor.level_index}</small>{message && <em>{message}</em>}</div><input accept=".pdf,image/png,image/jpeg,image/webp" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} ref={input} type="file" /><button disabled={!canEdit || busy} onClick={() => input.current?.click()} type="button">{busy ? "กำลังอัปโหลด…" : floor.has_plan ? "เปลี่ยนแปลน" : "อัปโหลดแปลน"}</button></article>;
}

export function ProjectSettingsWorkspace({ bimModels, floors, project }: { bimModels: BimModelList; floors: Floor[]; project: Project }) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("details");
  const [floorName, setFloorName] = useState("");
  const [levelIndex, setLevelIndex] = useState(String((floors.at(-1)?.level_index ?? 0) + 1));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [scopeEndDate, setScopeEndDate] = useState(project.structural_tracking_end_date ?? "");
  const [scopeBusy, setScopeBusy] = useState(false);
  const [scopeMessage, setScopeMessage] = useState<string | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);
  const canEdit = project.role === "admin";

  async function saveStructuralScope(event: FormEvent) {
    event.preventDefault();
    setScopeBusy(true);
    setScopeMessage(null);
    try {
      await responseBody(await fetch(`/api/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ structural_tracking_end_date: scopeEndDate || null }),
      }));
      setScopeMessage("บันทึกวันสิ้นสุดงานโครงสร้างแล้ว");
      router.refresh();
    } catch (error) {
      setScopeMessage(error instanceof Error ? error.message : "บันทึกไม่สำเร็จ");
    } finally {
      setScopeBusy(false);
    }
  }

  async function addFloor(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage(null);
    try {
      await responseBody(await fetch(`/api/projects/${project.id}/floors`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: floorName, level_index: Number(levelIndex), elevation_m: null }) }));
      setFloorName(""); setLevelIndex(String(Number(levelIndex) + 1)); setMessage("เพิ่มชั้นแล้ว — อัปโหลดแปลนต่อได้เลย"); router.refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "เพิ่มชั้นไม่สำเร็จ"); }
    finally { setBusy(false); }
  }

  async function deleteProject(event: FormEvent) {
    event.preventDefault();
    if (deleteConfirmation.trim() !== project.name) {
      setDeleteMessage("กรุณาพิมพ์ชื่อโครงการให้ตรงก่อนลบ");
      return;
    }
    setDeleteBusy(true);
    setDeleteMessage(null);
    try {
      await responseBody(await fetch(`/api/projects/${project.id}`, { method: "DELETE" }));
      router.replace("/projects");
      router.refresh();
    } catch (error) {
      setDeleteMessage(error instanceof Error ? error.message : "ลบโครงการไม่สำเร็จ");
      setDeleteBusy(false);
    }
  }

  const tabs: Array<{ id: Tab; label: string; done: boolean }> = [
    { id: "details", label: "1. รายละเอียด", done: Boolean(project.name && project.location) },
    { id: "floors", label: "2. ชั้นและแปลน", done: floors.length > 0 && floors.every((floor) => floor.has_plan) },
    { id: "bim", label: "3. BIM", done: Boolean(bimModels.active) },
    { id: "schedule", label: "4. แผนงาน", done: false },
    { id: "members", label: "5. สมาชิก", done: false },
  ];

  return <div className="project-settings-shell"><nav className="project-settings-tabs">{tabs.map((item) => <button className={tab === item.id ? "is-active" : ""} key={item.id} onClick={() => setTab(item.id)} type="button"><span>{item.label}</span><i>{item.done ? "✓" : "ไม่บังคับ"}</i></button>)}</nav>
    <section className="panel project-settings-content">
      {tab === "details" && <div className="settings-details"><p className="eyebrow">PROJECT DETAILS</p><h2>รายละเอียดโครงการ</h2><div className="settings-readonly-grid"><label><span>ชื่อโครงการ</span><strong>{project.name}</strong></label><label><span>ที่ตั้งโครงการ</span><strong>{project.location || "ยังไม่ระบุ"}</strong></label><label><span>เขตเวลา</span><strong>{project.timezone}</strong></label><label><span>สิทธิ์ของคุณ</span><strong>{project.role}</strong></label></div><p>{project.description || "ยังไม่มีคำอธิบายโครงการ"}</p>{canEdit && <form className="settings-add-floor" onSubmit={saveStructuralScope}><label><span>วันสุดท้ายของงานโครงสร้าง</span><input disabled={scopeBusy} onChange={(event) => setScopeEndDate(event.target.value)} type="date" value={scopeEndDate} /></label><button disabled={scopeBusy} type="submit">{scopeBusy ? "กำลังบันทึก…" : "บันทึกขอบเขต"}</button>{scopeMessage && <p className="notice" role="status">{scopeMessage}</p>}<small>Capture หลังวันนี้จะเก็บไว้ในระบบ แต่ไม่แสดงและไม่ถูกนำไปคำนวณ Progress โครงสร้าง</small></form>}<div className="settings-next"><span>กรอกชื่อและที่ตั้งแล้วจึงเพิ่มชั้นและแปลน</span><button onClick={() => setTab("floors")} type="button">ถัดไป: ชั้นและแปลน →</button></div>{canEdit && <form className="settings-danger-zone" onSubmit={deleteProject}><div><strong>ลบโครงการ</strong><p>ลบแปลน Capture, Virtual Tour, Progress, WBS และสมาชิกทั้งหมดของโครงการนี้อย่างถาวร</p></div><label><span>พิมพ์ชื่อโครงการเพื่อยืนยัน</span><input autoComplete="off" disabled={deleteBusy} onChange={(event) => setDeleteConfirmation(event.target.value)} placeholder={project.name} value={deleteConfirmation} /></label><button disabled={deleteBusy || deleteConfirmation.trim() !== project.name} type="submit">{deleteBusy ? "กำลังลบ…" : "ลบโครงการนี้"}</button>{deleteMessage && <p role="alert">{deleteMessage}</p>}</form>}</div>}
      {tab === "floors" && <div><div className="panel-header"><div><p className="eyebrow">FLOOR PLANS</p><h2>ชั้นและแปลนภาพรวม</h2><p>ใช้แปลนที่อ่านง่ายและมีรายละเอียดเท่าที่จำเป็นสำหรับวางเส้นทาง Capture</p></div><span>{floors.filter((floor) => floor.has_plan).length}/{floors.length} มีแปลน</span></div><div className="settings-floor-list">{floors.map((floor) => <FloorPlanRow canEdit={canEdit} floor={floor} key={floor.id} projectId={project.id} />)}</div>{canEdit && <form className="settings-add-floor" onSubmit={addFloor}><input onChange={(event) => setFloorName(event.target.value)} placeholder="ชื่อชั้น เช่น ชั้น 1" required value={floorName} /><input min="-10" onChange={(event) => setLevelIndex(event.target.value)} required type="number" value={levelIndex} /><button disabled={busy} type="submit">{busy ? "กำลังเพิ่ม…" : "+ เพิ่มชั้น"}</button></form>}{message && <p className="notice">{message}</p>}</div>}
      {tab === "bim" && <div><div className="panel-header"><div><p className="eyebrow">BIM MODEL</p><h2>อัปโหลดโมเดลโครงสร้าง</h2><p>ระบบรองรับ IFC จาก Revit และเก็บเวอร์ชันเดิมไว้ เมื่อตรวจ Capture แล้วจึงใช้จัดแนวโมเดลกับหน้างาน</p></div>{bimModels.active && <span>รุ่น {bimModels.active.version_no}</span>}</div>{bimModels.active ? <div className="settings-bim-current"><div><span>โมเดลที่ใช้งาน</span><strong>{bimModels.active.name}</strong><small>{(bimModels.active.size_bytes / 1024 / 1024).toFixed(1)} MB · {bimModels.active.ifc_schema}</small></div><BimModelUploader projectId={project.id} /></div> : <div className="settings-bim-empty"><strong>ยังไม่มีโมเดล BIM</strong><p>ส่งออก Revit เป็น IFC4 Reference View [Structural] แล้วเลือกไฟล์ด้านล่าง</p>{canEdit && <BimModelUploader projectId={project.id} />}</div>}<div className="settings-version-list">{bimModels.versions.map((model) => <span key={model.id}><b>รุ่น {model.version_no}</b>{model.name}<small>{new Date(model.created_at).toLocaleString("th-TH")}</small></span>)}</div></div>}
      {tab === "schedule" && <div className="settings-link-step"><span>04</span><h2>นำเข้าแผนงานโครงสร้าง</h2><p>ใช้ไฟล์ Excel ที่มี Name, WBS, Start และ Finish เพื่อสร้าง Planned Progress</p><Link className="button button-primary" href={`/projects/${project.id}/schedule`}>เปิดหน้าแผนงาน</Link></div>}
      {tab === "members" && <div className="settings-link-step"><span>05</span><h2>เชิญสมาชิกโครงการ</h2><p>กำหนดผู้ดูแล ผู้ตรวจ และผู้ดู เพื่อให้เพื่อนในกลุ่มช่วยตรวจ Progress ได้</p><Link className="button button-primary" href={`/projects/${project.id}/members`}>จัดการสมาชิก</Link></div>}
    </section>
  </div>;
}
