"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { PanoramaViewState } from "@/components/panorama-viewer";
import type { BimModel, CaptureDetail, Floor } from "@/lib/types";

type LoadingState = { percent: number; label: string };
type Keyframe = CaptureDetail["keyframes"][number];

type BimRuntime = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  renderer: THREE.WebGLRenderer;
  modelBounds: THREE.Box3;
  pathLayer: THREE.Group;
  pathPoints: THREE.Points | null;
  pathFrames: Keyframe[];
  pathPositions: Map<string, THREE.Vector3>;
  headingArrow: THREE.ArrowHelper | null;
};

type BimViewerProps = {
  model: BimModel;
  keyframes: Keyframe[];
  floors: Floor[];
  activeKeyframeId: string | null;
  panoramaView: PanoramaViewState;
  onSelectKeyframe?: (keyframeId: string) => void;
};

function allFinite(values: ArrayLike<number>) {
  for (let index = 0; index < values.length; index += 1) {
    if (!Number.isFinite(values[index])) return false;
  }
  return true;
}

function indexesFitVertexCount(values: ArrayLike<number>, vertexCount: number) {
  for (let index = 0; index < values.length; index += 1) {
    if (values[index] < 0 || values[index] >= vertexCount) return false;
  }
  return true;
}

function disposePathLayer(layer: THREE.Group) {
  for (const child of [...layer.children]) {
    child.traverse((object) => {
      if (object instanceof THREE.Line || object instanceof THREE.Points || object instanceof THREE.Mesh) {
        object.geometry.dispose();
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        for (const material of materials) material.dispose();
      }
    });
    layer.remove(child);
  }
}

function floorHeight(bounds: THREE.Box3, floor: Floor | undefined, floors: Floor[]) {
  const size = bounds.getSize(new THREE.Vector3());
  const ordered = [...floors].sort((first, second) => first.level_index - second.level_index);
  const floorIndex = Math.max(0, ordered.findIndex((item) => item.id === floor?.id));
  const denominator = Math.max(ordered.length, 1);
  return bounds.min.y + size.y * (0.1 + (floorIndex / denominator) * 0.75);
}

function createPlanToBimMapper(bounds: THREE.Box3) {
  // Camera poses are stored in normalized floor-plan coordinates. The project
  // sheets use a stable drawing viewport (the title block occupies the right
  // side), so keep one plan-to-BIM transform for every capture. Fitting each
  // individual walk to the model would make the same grid point move between
  // dates and would no longer represent a physical camera position.
  const minimumX = 0.22;
  const maximumX = 0.76;
  const minimumY = 0.24;
  const maximumY = 0.78;
  const rangeX = maximumX - minimumX;
  const rangeY = maximumY - minimumY;
  const size = bounds.getSize(new THREE.Vector3());
  const marginX = size.x * 0.08;
  const marginZ = size.z * 0.08;
  return (x: number, y: number, height: number) => new THREE.Vector3(
    bounds.min.x + marginX + ((x - minimumX) / rangeX) * Math.max(size.x - marginX * 2, 0.01),
    height,
    bounds.max.z - marginZ - ((y - minimumY) / rangeY) * Math.max(size.z - marginZ * 2, 0.01),
  );
}

export function BimViewer({
  model,
  keyframes,
  floors,
  activeKeyframeId,
  panoramaView,
  onSelectKeyframe,
}: BimViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const runtimeRef = useRef<BimRuntime | null>(null);
  const onSelectKeyframeRef = useRef(onSelectKeyframe);
  const [loading, setLoading] = useState<LoadingState>({ percent: 0, label: "กำลังดาวน์โหลด IFC" });
  const [error, setError] = useState<string | null>(null);
  const [runtimeVersion, setRuntimeVersion] = useState(0);
  const [followCamera, setFollowCamera] = useState(true);

  useEffect(() => {
    onSelectKeyframeRef.current = onSelectKeyframe;
  }, [onSelectKeyframe]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let cancelled = false;
    let frameId = 0;
    let resizeObserver: ResizeObserver | null = null;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf0f3f1);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 100000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.replaceChildren(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x53645c, 2.1));
    const sun = new THREE.DirectionalLight(0xffffff, 2.4);
    sun.position.set(20, 35, 18);
    scene.add(sun);

    const modelGroup = new THREE.Group();
    modelGroup.rotation.x = -Math.PI / 2;
    scene.add(modelGroup);
    const pathLayer = new THREE.Group();
    scene.add(pathLayer);
    const raycaster = new THREE.Raycaster();
    raycaster.params.Points = { threshold: 0.35 };
    const pointer = new THREE.Vector2();
    let pointerStart: { x: number; y: number } | null = null;

    function resize() {
      const width = Math.max(container!.clientWidth, 1);
      const height = Math.max(container!.clientHeight, 1);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    }

    function animate() {
      if (controls.enabled) controls.update();
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    }

    function pointerDown(event: PointerEvent) {
      pointerStart = { x: event.clientX, y: event.clientY };
    }

    function pointerUp(event: PointerEvent) {
      if (!pointerStart || Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 5) return;
      const runtime = runtimeRef.current;
      if (!runtime?.pathPoints) return;
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - bounds.left) / Math.max(bounds.width, 1)) * 2 - 1;
      pointer.y = -((event.clientY - bounds.top) / Math.max(bounds.height, 1)) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(runtime.pathPoints, false)[0];
      const frame = hit?.index === undefined ? null : runtime.pathFrames[hit.index];
      if (frame) onSelectKeyframeRef.current?.(frame.id);
    }

    async function loadIfc() {
      try {
        const response = await fetch(model.download_url);
        if (!response.ok) throw new Error(`ดาวน์โหลด IFC ไม่สำเร็จ (${response.status})`);
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (cancelled) return;
        setLoading({ percent: 18, label: "กำลังอ่านโครงสร้าง IFC" });

        const { IfcAPI } = await import("web-ifc");
        const ifc = new IfcAPI();
        ifc.SetWasmPath(`${window.location.origin}/api/bim/wasm/`, true);
        await ifc.Init();
        if (cancelled) {
          ifc.Dispose();
          return;
        }
        const modelId = ifc.OpenModel(bytes, {
          COORDINATE_TO_ORIGIN: true,
          CIRCLE_SEGMENTS: 16,
        });
        const materials = new Map<string, THREE.MeshPhongMaterial>();
        let skippedGeometries = 0;

        ifc.StreamAllMeshes(modelId, (flatMesh, index, total) => {
          if (cancelled) return;
          for (let i = 0; i < flatMesh.geometries.size(); i += 1) {
            const placed = flatMesh.geometries.get(i);
            const source = ifc.GetGeometry(modelId, placed.geometryExpressID);
            try {
              const vertexData = ifc.GetVertexArray(source.GetVertexData(), source.GetVertexDataSize());
              const indexData = ifc.GetIndexArray(source.GetIndexData(), source.GetIndexDataSize());
              const transformation = placed.flatTransformation;
              const vertexCount = vertexData.length / 6;

              // Some complex Revit reinforcement shapes are accepted by web-ifc,
              // but its triangulator can still return NaN coordinates. One invalid
              // mesh makes Three.js' scene bounds NaN and prevents the whole model
              // from rendering, so validate each placed geometry independently.
              if (
                vertexData.length === 0 ||
                vertexData.length % 6 !== 0 ||
                indexData.length === 0 ||
                !allFinite(vertexData) ||
                transformation.length !== 16 ||
                !allFinite(transformation) ||
                !allFinite(indexData) ||
                !indexesFitVertexCount(indexData, vertexCount)
              ) {
                skippedGeometries += 1;
                continue;
              }

              const positions = new Float32Array(vertexCount * 3);
              const normals = new Float32Array(vertexCount * 3);
              for (let sourceIndex = 0, targetIndex = 0; sourceIndex < vertexData.length; sourceIndex += 6, targetIndex += 3) {
                positions[targetIndex] = vertexData[sourceIndex];
                positions[targetIndex + 1] = vertexData[sourceIndex + 1];
                positions[targetIndex + 2] = vertexData[sourceIndex + 2];
                normals[targetIndex] = vertexData[sourceIndex + 3];
                normals[targetIndex + 1] = vertexData[sourceIndex + 4];
                normals[targetIndex + 2] = vertexData[sourceIndex + 5];
              }
              const geometry = new THREE.BufferGeometry();
              geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
              geometry.setAttribute("normal", new THREE.BufferAttribute(normals, 3));
              geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(indexData), 1));
              geometry.computeBoundingBox();
              if (!geometry.boundingBox || geometry.boundingBox.isEmpty()) {
                geometry.dispose();
                skippedGeometries += 1;
                continue;
              }

              const rawColor = placed.color;
              const r = Number.isFinite(rawColor.x) ? rawColor.x : 0.72;
              const g = Number.isFinite(rawColor.y) ? rawColor.y : 0.76;
              const b = Number.isFinite(rawColor.z) ? rawColor.z : 0.74;
              const opacity = Number.isFinite(rawColor.w) ? THREE.MathUtils.clamp(rawColor.w, 0.12, 1) : 1;
              const materialKey = `${r.toFixed(3)}:${g.toFixed(3)}:${b.toFixed(3)}:${opacity.toFixed(3)}`;
              let material = materials.get(materialKey);
              if (!material) {
                material = new THREE.MeshPhongMaterial({
                  color: new THREE.Color(r, g, b),
                  opacity,
                  transparent: opacity < 0.99,
                  side: THREE.DoubleSide,
                });
                materials.set(materialKey, material);
              }
              const mesh = new THREE.Mesh(geometry, material);
              mesh.applyMatrix4(new THREE.Matrix4().fromArray(transformation));
              modelGroup.add(mesh);
            } catch {
              // A malformed product must not prevent the remaining IFC products
              // from being shown. The exporter can be corrected separately.
              skippedGeometries += 1;
            } finally {
              const releasableSource = source as typeof source & { delete?: () => void };
              releasableSource.delete?.();
            }
          }
          // The browser build of web-ifc 0.0.77 can return FlatMesh as a
          // plain JavaScript object even though its type declaration exposes
          // an Embind `delete()` method. Only release it when that method is
          // actually present; otherwise calling it aborts the whole viewer.
          const releasableFlatMesh = flatMesh as typeof flatMesh & { delete?: () => void };
          releasableFlatMesh.delete?.();
          if (index % 25 === 0 || index + 1 === total) {
            setLoading({
              percent: 20 + Math.round(((index + 1) / Math.max(total, 1)) * 72),
              label: `กำลังสร้างโมเดล 3D ${index + 1}/${total}`,
            });
          }
        });

        ifc.CloseModel(modelId);
        ifc.Dispose();
        if (cancelled || modelGroup.children.length === 0) {
          if (!cancelled) throw new Error("ไม่พบรูปทรง 3D ในไฟล์ IFC")
          return;
        }

        modelGroup.updateMatrixWorld(true);
        const bounds = new THREE.Box3().setFromObject(modelGroup);
        const center = bounds.getCenter(new THREE.Vector3());
        const size = bounds.getSize(new THREE.Vector3());
        if (!allFinite(center.toArray()) || !allFinite(size.toArray()) || bounds.isEmpty()) {
          throw new Error("ขอบเขตโมเดล IFC ไม่ถูกต้อง กรุณา Export ใหม่โดยปิดหมวด Structural Rebar")
        }
        const radius = Math.max(size.x, size.y, size.z, 1);
        controls.target.copy(center);
        camera.position.copy(center).add(new THREE.Vector3(radius * 1.05, radius * 0.8, radius * 1.05));
        camera.near = Math.max(radius / 10000, 0.01);
        camera.far = radius * 50;
        camera.updateProjectionMatrix();
        controls.update();
        runtimeRef.current = {
          scene,
          camera,
          controls,
          renderer,
          modelBounds: bounds,
          pathLayer,
          pathPoints: null,
          pathFrames: [],
          pathPositions: new Map(),
          headingArrow: null,
        };
        setRuntimeVersion((version) => version + 1);
        setLoading({
          percent: 100,
          label: skippedGeometries > 0 ? `พร้อมใช้งาน (ข้ามรูปทรงที่เสีย ${skippedGeometries} ชิ้น)` : "พร้อมใช้งาน",
        });
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "เปิดโมเดล IFC ไม่สำเร็จ");
      }
    }

    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    resize();
    animate();
    void loadIfc();

    return () => {
      cancelled = true;
      cancelAnimationFrame(frameId);
      resizeObserver?.disconnect();
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      controls.dispose();
      disposePathLayer(pathLayer);
      if (runtimeRef.current?.renderer === renderer) runtimeRef.current = null;
      modelGroup.traverse((object) => {
        if (object instanceof THREE.Mesh) object.geometry.dispose();
      });
      const disposedMaterials = new Set<THREE.Material>();
      modelGroup.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        const objectMaterials = Array.isArray(object.material) ? object.material : [object.material];
        for (const material of objectMaterials) {
          if (!disposedMaterials.has(material)) material.dispose();
          disposedMaterials.add(material);
        }
      });
      renderer.dispose();
      container.replaceChildren();
    };
  }, [model.download_url]);

  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!runtime || runtimeVersion === 0) return;
    const activeFrame = keyframes.find((frame) => frame.id === activeKeyframeId && frame.pose)
      ?? keyframes.find((frame) => frame.pose);
    const activeFloorId = activeFrame?.pose?.floor_id;
    const floorFrames = keyframes
      .filter((frame) => frame.pose && frame.pose.floor_id === activeFloorId)
      .sort((first, second) => first.timestamp_ms - second.timestamp_ms);

    disposePathLayer(runtime.pathLayer);
    runtime.pathFrames = [];
    runtime.pathPositions = new Map();
    runtime.pathPoints = null;
    runtime.headingArrow = null;
    if (!activeFrame?.pose || floorFrames.length === 0) return;

    const activeFloor = floors.find((floor) => floor.id === activeFloorId);
    const height = floorHeight(runtime.modelBounds, activeFloor, floors);
    const mapToBim = createPlanToBimMapper(runtime.modelBounds);
    const routePositions: THREE.Vector3[] = [];
    const routeFrames: Keyframe[] = [];
    for (const frame of floorFrames) {
      const x = Number(frame.pose?.x);
      const y = Number(frame.pose?.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const position = mapToBim(x, y, height);
      routePositions.push(position);
      routeFrames.push(frame);
      runtime.pathPositions.set(frame.id, position);
    }
    if (routePositions.length === 0) return;

    const lineGeometry = new THREE.BufferGeometry().setFromPoints(routePositions);
    const line = new THREE.Line(lineGeometry, new THREE.LineBasicMaterial({
      color: 0x21c979,
      depthTest: false,
      transparent: true,
      opacity: 0.9,
    }));
    line.renderOrder = 10;
    runtime.pathLayer.add(line);

    const pointGeometry = new THREE.BufferGeometry().setFromPoints(routePositions);
    const points = new THREE.Points(pointGeometry, new THREE.PointsMaterial({
      color: 0x1ebf70,
      depthTest: false,
      size: 6,
      sizeAttenuation: false,
    }));
    points.renderOrder = 11;
    runtime.pathLayer.add(points);
    runtime.pathPoints = points;
    runtime.pathFrames = routeFrames;

    const activePosition = runtime.pathPositions.get(activeFrame.id);
    if (activePosition) {
      const modelSize = runtime.modelBounds.getSize(new THREE.Vector3());
      const markerRadius = Math.max(Math.min(Math.max(modelSize.x, modelSize.z) * 0.012, 0.35), 0.08);
      const activeMarker = new THREE.Mesh(
        new THREE.SphereGeometry(markerRadius, 20, 12),
        new THREE.MeshBasicMaterial({ color: 0x168de2, depthTest: false }),
      );
      activeMarker.position.copy(activePosition);
      activeMarker.renderOrder = 12;
      runtime.pathLayer.add(activeMarker);
    }
  }, [activeKeyframeId, floors, keyframes, runtimeVersion]);

  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!runtime || runtimeVersion === 0) return;
    runtime.controls.enabled = !followCamera;
    if (!followCamera) return;
    const activeFrame = keyframes.find((frame) => frame.id === activeKeyframeId && frame.pose);
    const routePosition = activeFrame ? runtime.pathPositions.get(activeFrame.id) : null;
    if (!activeFrame?.pose || !routePosition) return;

    const modelSize = runtime.modelBounds.getSize(new THREE.Vector3());
    const eyeHeight = THREE.MathUtils.clamp(modelSize.y * 0.075, 0.8, 1.8);
    const cameraPosition = routePosition.clone().add(new THREE.Vector3(0, eyeHeight, 0));
    const heading = THREE.MathUtils.degToRad(Number(activeFrame.pose.heading_deg) + panoramaView.longitude);
    const pitch = THREE.MathUtils.degToRad(panoramaView.latitude);
    const direction = new THREE.Vector3(
      Math.cos(heading) * Math.cos(pitch),
      Math.sin(pitch),
      -Math.sin(heading) * Math.cos(pitch),
    ).normalize();

    runtime.camera.position.copy(cameraPosition);
    runtime.camera.up.set(0, 1, 0);
    runtime.camera.lookAt(cameraPosition.clone().add(direction));
    runtime.camera.fov = THREE.MathUtils.clamp(panoramaView.fov, 35, 95);
    runtime.camera.near = Math.max(Math.max(modelSize.x, modelSize.y, modelSize.z) / 20000, 0.01);
    runtime.camera.far = Math.max(Math.max(modelSize.x, modelSize.y, modelSize.z) * 60, 100);
    runtime.camera.updateProjectionMatrix();
    runtime.camera.updateMatrixWorld(true);

    if (runtime.headingArrow) {
      runtime.pathLayer.remove(runtime.headingArrow);
      runtime.headingArrow.dispose();
    }
    const arrowLength = Math.max(Math.min(Math.max(modelSize.x, modelSize.z) * 0.055, 1.5), 0.35);
    const horizontalDirection = new THREE.Vector3(direction.x, 0, direction.z).normalize();
    const arrow = new THREE.ArrowHelper(horizontalDirection, routePosition, arrowLength, 0x168de2, arrowLength * 0.35, arrowLength * 0.22);
    arrow.line.renderOrder = 13;
    arrow.cone.renderOrder = 13;
    (arrow.line.material as THREE.Material).depthTest = false;
    (arrow.cone.material as THREE.Material).depthTest = false;
    runtime.pathLayer.add(arrow);
    runtime.headingArrow = arrow;
  }, [activeKeyframeId, followCamera, keyframes, panoramaView, runtimeVersion]);

  return (
    <section className="bim-viewer-shell">
      <div className="bim-canvas" ref={containerRef} />
      <div className="bim-model-label">
        <span>BIM รุ่น {model.version_no}</span>
        <strong>{model.name}</strong>
      </div>
      {!error && loading.percent === 100 && (
        <div className="bim-sync-toolbar">
          <button
            className={followCamera ? "is-active" : ""}
            onClick={() => setFollowCamera((current) => !current)}
            type="button"
          >
            {followCamera ? "กำลังตามกล้อง 360°" : "ดูโมเดลอิสระ"}
          </button>
          <span><i /> เส้นทางกล้องจริง · คลิกจุดเพื่อเปิดภาพ 360°</span>
        </div>
      )}
      {loading.percent < 100 && !error && (
        <div className="bim-loading" role="status">
          <strong>{loading.label}</strong>
          <progress max="100" value={loading.percent} />
          <span>{loading.percent}%</span>
        </div>
      )}
      {error && <div className="bim-error" role="alert"><strong>เปิด BIM ไม่สำเร็จ</strong><span>{error}</span></div>}
      {!error && loading.percent === 100 && (
        <div className="bim-help">
          {followCamera
            ? "BIM อยู่ที่ Camera Pose และหันตามภาพ 360° แบบเรียลไทม์"
            : "ลากเพื่อหมุน · ล้อเมาส์เพื่อซูม · กดปุ่มด้านบนเพื่อกลับไปตามกล้อง"}
        </div>
      )}
    </section>
  );
}
