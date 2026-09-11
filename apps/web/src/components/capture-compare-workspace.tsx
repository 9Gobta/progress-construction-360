"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { PanoramaViewer, type PanoramaViewState } from "@/components/panorama-viewer";
import type { Capture, CaptureDetail, Floor } from "@/lib/types";

function nearestFrame(sourceId: string, source: CaptureDetail, target: CaptureDetail) {
  const point = source.keyframes.find((frame) => frame.id === sourceId)?.pose;
  if (!point) return null;
  const candidates = target.keyframes.filter((frame) => frame.pose?.floor_id === point.floor_id && frame.is_warp_point);
  return candidates.reduce<(typeof candidates)[number] | null>((best, frame) => {
    if (!frame.pose) return best;
    if (!best?.pose) return frame;
    const distance = Math.hypot(Number(frame.pose.x) - Number(point.x), Number(frame.pose.y) - Number(point.y));
    const bestDistance = Math.hypot(Number(best.pose.x) - Number(point.x), Number(best.pose.y) - Number(point.y));
    return distance < bestDistance ? frame : best;
  }, null)?.id ?? null;
}

export function CaptureCompareWorkspace({ projectId, captures, floors, left, right }: {
  projectId: string;
  captures: Capture[];
  floors: Floor[];
  left: CaptureDetail;
  right: CaptureDetail;
}) {
  const router = useRouter();
  const [locked, setLocked] = useState(true);
  const [leftFrame, setLeftFrame] = useState<string | null>(left.keyframes.find((item) => item.is_warp_point)?.id ?? left.keyframes[0]?.id ?? null);
  const [rightFrame, setRightFrame] = useState<string | null>(right.keyframes.find((item) => item.is_warp_point)?.id ?? right.keyframes[0]?.id ?? null);
  const [leftView, setLeftView] = useState<PanoramaViewState | null>(null);
  const [rightView, setRightView] = useState<PanoramaViewState | null>(null);
  const [leftToken, setLeftToken] = useState(0);
  const [rightToken, setRightToken] = useState(0);
  const options = useMemo(() => [...captures].sort((a, b) => a.captured_at.localeCompare(b.captured_at)), [captures]);

  function navigate(side: "left" | "right", id: string) {
    const nextLeft = side === "left" ? id : left.capture.id;
    const nextRight = side === "right" ? id : right.capture.id;
    router.replace(`/projects/${projectId}/compare?left=${nextLeft}&right=${nextRight}`);
  }
  function select(side: "left" | "right", id: string | null) {
    if (!id) return;
    if (side === "left") {
      setLeftFrame(id);
      if (locked) setRightFrame(nearestFrame(id, left, right));
    } else {
      setRightFrame(id);
      if (locked) setLeftFrame(nearestFrame(id, right, left));
    }
  }
  function syncView(side: "left" | "right", view: PanoramaViewState) {
    if (!locked) return;
    if (side === "left") { setRightView(view); setRightToken((value) => value + 1); }
    else { setLeftView(view); setLeftToken((value) => value + 1); }
  }

  return <section className="compare-workspace">
    <header><div><span>เปรียบเทียบตำแหน่งเดียวกัน</span><strong>ภาพ 360 ต่างวัน</strong></div><button className={locked ? "is-locked" : ""} onClick={() => setLocked((value) => !value)} type="button">{locked ? "🔒 ล็อกมุมมองร่วมกัน" : "🔓 แยกมุมมอง"}</button></header>
    <div className="compare-grid">
      <article><label>ฝั่งก่อนหน้า<select onChange={(event) => navigate("left", event.target.value)} value={left.capture.id}>{options.map((capture) => <option key={capture.id} value={capture.id}>{new Date(capture.captured_at).toLocaleString("th-TH")}</option>)}</select></label><div><PanoramaViewer canEdit={false} detail={left} floors={floors} onSelectedKeyframeChange={(id) => select("left", id)} onViewStateChange={(view) => syncView("left", view)} projectId={projectId} requestedKeyframeId={leftFrame} requestedViewState={leftView} requestedViewSyncToken={leftToken} /></div></article>
      <article><label>ฝั่งเปรียบเทียบ<select onChange={(event) => navigate("right", event.target.value)} value={right.capture.id}>{options.map((capture) => <option key={capture.id} value={capture.id}>{new Date(capture.captured_at).toLocaleString("th-TH")}</option>)}</select></label><div><PanoramaViewer canEdit={false} detail={right} floors={floors} onSelectedKeyframeChange={(id) => select("right", id)} onViewStateChange={(view) => syncView("right", view)} projectId={projectId} requestedKeyframeId={rightFrame} requestedViewState={rightView} requestedViewSyncToken={rightToken} /></div></article>
    </div>
  </section>;
}
