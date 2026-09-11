"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { PanoramaViewState } from "@/components/panorama-viewer";
import { categoryFromIfcType, type BimCategoryKey } from "@/lib/bim-categories";
import {
  fitPlanToIfc,
  planDirectionInThree,
  transformPlanPoint,
  validatePlanToIfcOrientation,
  type PlanToIfcTransform,
} from "@/lib/bim-registration";
import type { BimModel, BimViewpoint, CaptureDetail, StructuralElement } from "@/lib/types";

type LoadingState = { percent: number; label: string };
type Keyframe = CaptureDetail["keyframes"][number];
type BimViewMode = "follow" | "inspect" | "free";
const BIM_CATEGORIES: Array<{ key: BimCategoryKey; label: string }> = [
  { key: "frame", label: "เสา/คาน" },
  { key: "slab", label: "พื้น/หลังคา" },
  { key: "stair", label: "บันได" },
  { key: "rebar", label: "เหล็กเสริม" },
  { key: "other", label: "อื่น ๆ" },
];

type BimRuntime = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  renderer: THREE.WebGLRenderer;
  inspectionLight: THREE.DirectionalLight;
  modelGroup: THREE.Group;
  modelBounds: THREE.Box3;
  pathLayer: THREE.Group;
  pathPoints: THREE.Points | null;
  pathFrames: Keyframe[];
  pathPositions: Map<string, THREE.Vector3>;
  headingArrow: THREE.ArrowHelper | null;
  planOverlay: THREE.Mesh | null;
  planToBim: PlanToBimRegistration | null;
  productBounds: Map<string, THREE.Box3>;
  productMeshes: THREE.Mesh[];
  cameraTransition: {
    startedAt: number;
    durationMs: number;
    fromPosition: THREE.Vector3;
    toPosition: THREE.Vector3;
    fromTarget: THREE.Vector3;
    toTarget: THREE.Vector3;
    fromUp: THREE.Vector3;
    toUp: THREE.Vector3;
  } | null;
  mirrorFollowProjection: boolean;
};

type PlanToBimRegistration = {
  map: (x: number, y: number, height: number) => THREE.Vector3;
  direction: (headingDeg: number) => THREE.Vector3 | null;
  matchedElementCount: number;
  rmsErrorMeters: number;
  cameraHeight: number;
};

type BimViewerProps = {
  model: BimModel;
  keyframes: Keyframe[];
  activeKeyframeId: string | null;
  panoramaView: PanoramaViewState;
  structuralElements: StructuralElement[];
  planImageUrl?: string | null;
  canSaveViewpoint?: boolean;
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

function structuralElementCenter(element: StructuralElement): [number, number] | null {
  const points = element.geometry_json.footprint ?? element.geometry_json.line ?? [];
  if (points.length === 0) return null;
  const x = points.reduce((sum, point) => sum + Number(point[0]), 0) / points.length;
  const y = points.reduce((sum, point) => sum + Number(point[1]), 0) / points.length;
  return Number.isFinite(x) && Number.isFinite(y) ? [x, y] : null;
}

function median(values: number[]) {
  const ordered = [...values].sort((first, second) => first - second);
  return ordered.length ? ordered[Math.floor(ordered.length / 2)] : 0;
}

function visibleBimBounds(runtime: BimRuntime) {
  const bounds = new THREE.Box3();
  for (const mesh of runtime.productMeshes) {
    if (!mesh.visible) continue;
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    if (!mesh.geometry.boundingBox) continue;
    mesh.updateWorldMatrix(true, false);
    bounds.union(mesh.geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
  }
  return bounds.isEmpty() ? new THREE.Box3().setFromObject(runtime.modelGroup) : bounds;
}

function updateBimProjection(camera: THREE.PerspectiveCamera, mirrorHorizontal = false) {
  camera.updateProjectionMatrix();
  if (!mirrorHorizontal) return;
  // A mirrored IFC has opposite screen handedness even after its plan position
  // and forward heading are correct. Reflect only the rendered horizontal axis
  // in follow mode; route coordinates and camera direction remain untouched.
  camera.projectionMatrix.elements[0] *= -1;
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
}

function createRegisteredPlanToBimMapper(
  productBounds: Map<string, THREE.Box3>,
  elements: StructuralElement[],
): PlanToBimRegistration | null {
  const elementByGlobalId = new Map(elements.map((element) => [element.ifc_global_id, element]));
  const pairs: Array<{ plan: [number, number]; ifc: [number, number]; element: StructuralElement }> = [];
  for (const [globalId, bounds] of productBounds) {
    const element = elementByGlobalId.get(globalId);
    const plan = element ? structuralElementCenter(element) : null;
    if (!element || !plan || bounds.isEmpty()) continue;
    const center = bounds.getCenter(new THREE.Vector3());
    if (Number.isFinite(center.x) && Number.isFinite(center.z)) {
      // web-ifc's streamed mesh transformations are already converted to a
      // Y-up viewer frame. X/Z are the floor plane and Y is elevation. Keep
      // the registration math in the IFC X/Y convention by negating viewer Z.
      pairs.push({ plan, ifc: [center.x, -center.z], element });
    }
  }
  if (pairs.length < 6) return null;

  // Revit can export foundations, pedestals and columns through different
  // placement hierarchies. Fit coherent element classes independently, then
  // use the best verified transform instead of letting one hierarchy pull the
  // camera away from the plan. This also rejects the known reviewed column
  // relocation at grid 1/D as an outlier.
  const candidateGroups = ["FOUNDATION", "PEDESTAL", "COLUMN"]
    .map((kind) => pairs.filter((pair) => pair.element.element_kind === kind))
    .filter((group) => group.length >= 6);
  candidateGroups.push(pairs);
  let best: {
    fit: PlanToIfcTransform;
    inliers: typeof pairs;
    rmsErrorMeters: number;
  } | null = null;
  for (const candidate of candidateGroups) {
    let fit = fitPlanToIfc(candidate);
    if (!fit) continue;
    const firstErrors = candidate.map((pair) => {
      const predicted = transformPlanPoint(fit!, ...pair.plan);
      return Math.hypot(predicted[0] - pair.ifc[0], predicted[1] - pair.ifc[1]);
    });
    const threshold = Math.max(0.25, median(firstErrors) * 3);
    const inliers = candidate.filter((_pair, index) => firstErrors[index] <= threshold);
    if (inliers.length < 6) continue;
    fit = fitPlanToIfc(inliers);
    if (!fit || !validatePlanToIfcOrientation(fit).valid) continue;
    const rmsErrorMeters = Math.sqrt(inliers.reduce((sum, pair) => {
      const predicted = transformPlanPoint(fit!, ...pair.plan);
      return sum + (predicted[0] - pair.ifc[0]) ** 2 + (predicted[1] - pair.ifc[1]) ** 2;
    }, 0) / inliers.length);
    if (Number.isFinite(rmsErrorMeters) && (!best || rmsErrorMeters < best.rmsErrorMeters)) {
      best = { fit, inliers, rmsErrorMeters };
    }
  }
  if (!best || best.rmsErrorMeters > 0.35) return null;

  const columnBaseElevations = pairs
    .filter((pair) => pair.element.element_kind === "COLUMN")
    .map((pair) => productBounds.get(pair.element.ifc_global_id)?.min.y)
    .filter((value): value is number => value !== undefined && Number.isFinite(value));
  const fallbackElevations = best.inliers
    .map((pair) => productBounds.get(pair.element.ifc_global_id)?.min.y)
    .filter((value): value is number => value !== undefined && Number.isFinite(value));
  const baseElevation = median(columnBaseElevations.length ? columnBaseElevations : fallbackElevations);
  const cameraHeight = baseElevation + 1.55;
  const planTransform = best.fit;
  return {
    map: (x, y, height) => {
      const [ifcX, ifcY] = transformPlanPoint(planTransform, x, y);
      // The IFC viewer rotates Z-up geometry into Three.js' Y-up convention.
      return new THREE.Vector3(ifcX, height, -ifcY);
    },
    direction: (headingDeg) => {
      const direction = planDirectionInThree(planTransform, headingDeg);
      return direction ? new THREE.Vector3(...direction) : null;
    },
    matchedElementCount: best.inliers.length,
    rmsErrorMeters: best.rmsErrorMeters,
    cameraHeight,
  };
}

export function BimViewer({
  model,
  keyframes,
  activeKeyframeId,
  panoramaView,
  structuralElements,
  planImageUrl = null,
  canSaveViewpoint = false,
  onSelectKeyframe,
}: BimViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewCubeRef = useRef<HTMLDivElement>(null);
  const runtimeRef = useRef<BimRuntime | null>(null);
  const onSelectKeyframeRef = useRef(onSelectKeyframe);
  const [loading, setLoading] = useState<LoadingState>({ percent: 0, label: "กำลังดาวน์โหลด IFC" });
  const [error, setError] = useState<string | null>(null);
  const [runtimeVersion, setRuntimeVersion] = useState(0);
  const [viewMode, setViewMode] = useState<BimViewMode>("follow");
  const [mirrorModel, setMirrorModel] = useState(true);
  const [registration, setRegistration] = useState<PlanToBimRegistration | null>(null);
  const [categoryCounts, setCategoryCounts] = useState<Record<BimCategoryKey, number>>({
    frame: 0, slab: 0, stair: 0, rebar: 0, other: 0,
  });
  const [visibleCategories, setVisibleCategories] = useState<Record<BimCategoryKey, boolean>>({
    frame: true, slab: true, stair: true, rebar: false, other: false,
  });
  const [savedViewpoint, setSavedViewpoint] = useState<BimViewpoint | null>(null);
  const [viewpointStatus, setViewpointStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [viewpointApiAvailable, setViewpointApiAvailable] = useState(false);

  useEffect(() => {
    onSelectKeyframeRef.current = onSelectKeyframe;
  }, [onSelectKeyframe]);

  useEffect(() => {
    const controller = new AbortController();
    if (!activeKeyframeId) return () => controller.abort();
    fetch(`/api/projects/${model.project_id}/bim-models/${model.id}/viewpoints/${activeKeyframeId}`, {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("load viewpoint failed");
        return response.json() as Promise<BimViewpoint | null>;
      })
      .then((viewpoint) => {
        setSavedViewpoint(viewpoint);
        setViewpointApiAvailable(true);
        setViewpointStatus((current) => current === "saving" ? current : "idle");
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setViewpointApiAvailable(false);
        setViewpointStatus("error");
      });
    return () => controller.abort();
  }, [activeKeyframeId, model.id, model.project_id]);

  function applySavedViewpoint(viewpoint: BimViewpoint | null = savedViewpoint) {
    const runtime = runtimeRef.current;
    if (!runtime || !viewpoint || viewpoint.keyframe_id !== activeKeyframeId) return;
    setViewMode("free");
    runtime.mirrorFollowProjection = false;
    runtime.camera.position.set(viewpoint.position_x, viewpoint.position_y, viewpoint.position_z);
    runtime.controls.target.set(viewpoint.target_x, viewpoint.target_y, viewpoint.target_z);
    runtime.camera.fov = viewpoint.fov;
    updateBimProjection(runtime.camera);
    runtime.controls.enabled = true;
    runtime.controls.update();
  }

  async function saveCurrentViewpoint() {
    const runtime = runtimeRef.current;
    if (!runtime || !activeKeyframeId || !canSaveViewpoint) return;
    setViewpointStatus("saving");
    try {
      const response = await fetch(
        `/api/projects/${model.project_id}/bim-models/${model.id}/viewpoints/${activeKeyframeId}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            position_x: runtime.camera.position.x,
            position_y: runtime.camera.position.y,
            position_z: runtime.camera.position.z,
            target_x: runtime.controls.target.x,
            target_y: runtime.controls.target.y,
            target_z: runtime.controls.target.z,
            fov: runtime.camera.fov,
          }),
        },
      );
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail ?? "บันทึกมุม BIM ไม่สำเร็จ");
      setSavedViewpoint(body as BimViewpoint);
      setViewpointStatus("saved");
    } catch {
      setViewpointStatus("error");
    }
  }

  function frameBimView(direction: THREE.Vector3, up = new THREE.Vector3(0, 1, 0)) {
    const runtime = runtimeRef.current;
    if (!runtime) return;
    setViewMode("free");
    runtime.mirrorFollowProjection = false;
    runtime.controls.enabled = true;
    runtime.modelGroup.updateMatrixWorld(true);
    const bounds = visibleBimBounds(runtime);
    if (bounds.isEmpty()) return;
    const target = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const radius = Math.max(size.length() * 0.5, 1);
    const verticalFov = THREE.MathUtils.degToRad(42);
    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * runtime.camera.aspect);
    const distance = Math.max(
      size.y / Math.max(2 * Math.tan(verticalFov / 2), 0.01),
      Math.max(size.x, size.z) / Math.max(2 * Math.tan(horizontalFov / 2), 0.01),
      radius,
    ) * 1.18;
    runtime.cameraTransition = {
      startedAt: performance.now(),
      durationMs: 320,
      fromPosition: runtime.camera.position.clone(),
      toPosition: target.clone().add(direction.clone().normalize().multiplyScalar(distance)),
      fromTarget: runtime.controls.target.clone(),
      toTarget: target,
      fromUp: runtime.camera.up.clone(),
      toUp: up.clone().normalize(),
    };
    runtime.camera.fov = 42;
    runtime.camera.near = Math.max(radius / 10000, 0.01);
    runtime.camera.far = Math.max(radius * 60, 100);
    updateBimProjection(runtime.camera);
  }

  function rotateBimQuarterTurn(direction: -1 | 1) {
    const runtime = runtimeRef.current;
    if (!runtime) return;
    const offset = runtime.camera.position.clone().sub(runtime.controls.target);
    if (offset.lengthSq() < 1e-8) return;
    const rotated = offset.applyAxisAngle(new THREE.Vector3(0, 1, 0), direction * Math.PI / 2);
    frameBimView(rotated, new THREE.Vector3(0, 1, 0));
  }

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
    controls.zoomToCursor = true;
    controls.zoomSpeed = 1.35;
    controls.panSpeed = 1;
    controls.rotateSpeed = 0.72;
    controls.mouseButtons.LEFT = null;
    controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN;
    controls.mouseButtons.RIGHT = null;
    controls.touches.ONE = THREE.TOUCH.ROTATE;
    controls.touches.TWO = THREE.TOUCH.DOLLY_PAN;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x53645c, 2.1));
    const sun = new THREE.DirectionalLight(0xffffff, 2.4);
    sun.position.set(20, 35, 18);
    scene.add(sun);
    const inspectionLight = new THREE.DirectionalLight(0xffffff, 2.2);
    inspectionLight.position.set(0, -35, 0);
    inspectionLight.visible = false;
    scene.add(inspectionLight);

    // web-ifc has already converted its streamed geometry to Three.js' Y-up
    // frame. Rotating it again lays the building on its side and swaps the
    // walking plane with elevation.
    const modelGroup = new THREE.Group();
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
      const runtime = runtimeRef.current;
      updateBimProjection(
        camera,
        runtime?.renderer === renderer && runtime.mirrorFollowProjection,
      );
      renderer.setSize(width, height, false);
    }

    function animate() {
      const runtime = runtimeRef.current;
      if (runtime?.renderer === renderer && runtime.cameraTransition) {
        const transition = runtime.cameraTransition;
        const elapsed = (performance.now() - transition.startedAt) / transition.durationMs;
        const progress = THREE.MathUtils.clamp(elapsed, 0, 1);
        const eased = progress * progress * (3 - 2 * progress);
        camera.position.lerpVectors(transition.fromPosition, transition.toPosition, eased);
        camera.up.lerpVectors(transition.fromUp, transition.toUp, eased).normalize();
        controls.target.lerpVectors(transition.fromTarget, transition.toTarget, eased);
        if (progress >= 1) runtime.cameraTransition = null;
      }
      if (controls.enabled) controls.update();
      const viewCube = viewCubeRef.current;
      if (viewCube) {
        const cameraOffset = camera.position.clone().sub(controls.target);
        // Follow mode can mirror only the rendered horizontal projection so a
        // reflected IFC has the same left/right layout as the panorama. Apply
        // that same screen convention to the ViewCube; otherwise the model is
        // correct while the cube misleadingly reports the opposite side.
        const displayedX = runtime?.mirrorFollowProjection
          ? -cameraOffset.x
          : cameraOffset.x;
        const horizontal = Math.hypot(displayedX, cameraOffset.z);
        const yaw = Math.atan2(displayedX, cameraOffset.z);
        const pitch = Math.atan2(cameraOffset.y, Math.max(horizontal, 1e-8));
        viewCube.style.transform = `rotateX(${-pitch}rad) rotateY(${yaw}rad)`;
        for (const face of viewCube.querySelectorAll<HTMLButtonElement>("button")) {
          face.style.pointerEvents = "none";
        }
        const visibleFaces = [
          cameraOffset.z >= 0 ? ".is-front" : ".is-back",
          displayedX >= 0 ? ".is-left" : ".is-right",
          cameraOffset.y >= 0 ? ".is-top" : ".is-bottom",
        ];
        for (const selector of visibleFaces) {
          const face = viewCube.querySelector<HTMLButtonElement>(selector);
          if (face) face.style.pointerEvents = "auto";
        }
      }
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    }

    function pointerDown(event: PointerEvent) {
      if (event.button === 1) {
        controls.mouseButtons.MIDDLE = event.shiftKey ? THREE.MOUSE.ROTATE : THREE.MOUSE.PAN;
      }
      pointerStart = { x: event.clientX, y: event.clientY };
    }

    function pointerUp(event: PointerEvent) {
      controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN;
      if (event.button !== 0) return;
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
        const productBounds = new Map<string, THREE.Box3>();
        const productMeshes: THREE.Mesh[] = [];
        const loadedCategoryCounts: Record<BimCategoryKey, number> = {
          frame: 0, slab: 0, stair: 0, rebar: 0, other: 0,
        };
        let skippedGeometries = 0;

        ifc.StreamAllMeshes(modelId, (flatMesh, index, total) => {
          if (cancelled) return;
          let globalId: string | null = null;
          try {
            const product = ifc.GetLine(modelId, flatMesh.expressID, false) as {
              GlobalId?: { value?: unknown };
            };
            globalId = typeof product?.GlobalId?.value === "string" ? product.GlobalId.value : null;
          } catch {
            // Geometry without an IFC GlobalId can still be shown in free-view mode,
            // but it cannot be trusted for plan registration or floor isolation.
          }
          let ifcTypeName = "IFCUNKNOWN";
          try {
            ifcTypeName = ifc.GetNameFromTypeCode(ifc.GetLineType(modelId, flatMesh.expressID)) || ifcTypeName;
          } catch {
            // Unknown vendor entities remain visible through the "อื่น ๆ"
            // filter instead of aborting the complete IFC stream.
          }
          const bimCategory = categoryFromIfcType(ifcTypeName);
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
              mesh.userData.ifcGlobalId = globalId;
              mesh.userData.ifcTypeName = ifcTypeName;
              mesh.userData.bimCategory = bimCategory;
              mesh.userData.bimFloorVisible = true;
              mesh.updateMatrixWorld(true);
              const placedBounds = new THREE.Box3().setFromObject(mesh);
              if (!placedBounds.isEmpty()) {
                mesh.userData.ifcBounds = placedBounds.clone();
                if (globalId) {
                  const existingBounds = productBounds.get(globalId);
                  if (existingBounds) existingBounds.union(placedBounds);
                  else productBounds.set(globalId, placedBounds.clone());
                }
              }
              productMeshes.push(mesh);
              loadedCategoryCounts[bimCategory] += 1;
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
        const fullBounds = new THREE.Box3().setFromObject(modelGroup);
        const planToBim = createRegisteredPlanToBimMapper(productBounds, structuralElements);
        if (planToBim) {
          const floorBaseElevation = planToBim.cameraHeight - 1.55;
          const floorMinimum = floorBaseElevation - 0.25;
          const floorMaximum = floorBaseElevation + 3.2;
          for (const mesh of productMeshes) {
            const meshBounds = mesh.userData.ifcBounds;
            mesh.userData.bimFloorVisible = meshBounds instanceof THREE.Box3
              && meshBounds.min.y >= floorMinimum
              && meshBounds.min.y < floorMaximum;
            const category = mesh.userData.bimCategory as BimCategoryKey;
            mesh.visible = Boolean(mesh.userData.bimFloorVisible) && visibleCategories[category];
          }
          modelGroup.updateMatrixWorld(true);
        }
        const floorBounds = planToBim ? new THREE.Box3().setFromObject(modelGroup) : null;
        const bounds = floorBounds && !floorBounds.isEmpty() ? floorBounds : fullBounds;
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
        updateBimProjection(camera);
        controls.update();
        runtimeRef.current = {
          scene,
          camera,
          controls,
          renderer,
          inspectionLight,
          modelGroup,
          modelBounds: bounds,
          pathLayer,
          pathPoints: null,
          pathFrames: [],
          pathPositions: new Map(),
          headingArrow: null,
          planOverlay: null,
          planToBim,
          productBounds,
          productMeshes,
          cameraTransition: null,
          mirrorFollowProjection: false,
        };
        setCategoryCounts(loadedCategoryCounts);
        setRegistration(planToBim);
        setViewMode(planToBim ? "inspect" : "free");
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
    renderer.domElement.addEventListener("pointerdown", pointerDown, { capture: true });
    renderer.domElement.addEventListener("pointerup", pointerUp);
    resize();
    animate();
    void loadIfc();

    return () => {
      cancelled = true;
      cancelAnimationFrame(frameId);
      resizeObserver?.disconnect();
      renderer.domElement.removeEventListener("pointerdown", pointerDown, { capture: true });
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      controls.dispose();
      disposePathLayer(pathLayer);
      if (runtimeRef.current?.renderer === renderer) runtimeRef.current = null;
      setRegistration(null);
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
  // Category visibility is deliberately not a load dependency: toggling a
  // filter must not download and parse the IFC again.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model.download_url, structuralElements]);

  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!runtime || runtimeVersion === 0) return;
    for (const mesh of runtime.productMeshes) {
      const category = mesh.userData.bimCategory as BimCategoryKey;
      mesh.visible = Boolean(mesh.userData.bimFloorVisible) && visibleCategories[category];
    }
  }, [runtimeVersion, visibleCategories]);

  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!runtime || runtimeVersion === 0) return;
    runtime.modelGroup.matrixAutoUpdate = false;
    runtime.modelGroup.matrix.identity();
    if (mirrorModel && runtime.planToBim) {
      // Keep the registered plan, route and camera poses fixed. Only reflect
      // IFC geometry across the building centre along the plan Y direction;
      // this moves the exported foundation side back to the bottom of the
      // drawing without changing any capture/localization data.
      const planYAxis = runtime.planToBim.direction(90)?.normalize();
      if (planYAxis) {
        const structuralCenters = structuralElements
          .map(structuralElementCenter)
          .filter((point): point is [number, number] => point !== null);
        const planCenterX = structuralCenters.length
          ? (Math.min(...structuralCenters.map((point) => point[0])) + Math.max(...structuralCenters.map((point) => point[0]))) / 2
          : 0.5;
        const planCenterY = structuralCenters.length
          ? (Math.min(...structuralCenters.map((point) => point[1])) + Math.max(...structuralCenters.map((point) => point[1]))) / 2
          : 0.5;
        const modelCenter = runtime.modelBounds.getCenter(new THREE.Vector3());
        const defaultCenter = runtime.planToBim.map(planCenterX, planCenterY, modelCenter.y);
        const nx = planYAxis.x;
        const ny = planYAxis.y;
        const nz = planYAxis.z;

        // Mirroring swaps the physical top/bottom grid rows, so pairing a
        // mirrored member back to the same IFC GlobalId is incorrect: a
        // column from row A now occupies row D. Align the reflected model by
        // the outer column-grid extents instead. This keeps the route and plan
        // fixed, puts the IFC column axes back on the drawing grid, and avoids
        // foundations, stairs or raised beams shifting the whole model.
        const columnAnchors = structuralElements.flatMap((element) => {
          if (element.element_kind !== "COLUMN") return [];
          const planCenter = structuralElementCenter(element);
          const bounds = runtime.productBounds.get(element.ifc_global_id);
          if (!planCenter || !bounds || bounds.isEmpty()) return [];
          const source = bounds.getCenter(new THREE.Vector3());
          const target = runtime.planToBim!.map(planCenter[0], planCenter[1], source.y);
          return [{ source, target }];
        });
        const center = defaultCenter.clone();
        const tangentCorrection = new THREE.Vector3();
        if (columnAnchors.length >= 6) {
          const sourceProjections = columnAnchors.map((pair) => pair.source.dot(planYAxis));
          const targetProjections = columnAnchors.map((pair) => pair.target.dot(planYAxis));
          const desiredPlaneProjection = (
            Math.max(...sourceProjections) + Math.min(...targetProjections)
          ) / 2;
          center.addScaledVector(planYAxis, desiredPlaneProjection - center.dot(planYAxis));

          const tangentAxis = new THREE.Vector3(-planYAxis.z, 0, planYAxis.x).normalize();
          const sourceTangent = columnAnchors.map((pair) => pair.source.dot(tangentAxis));
          const targetTangent = columnAnchors.map((pair) => pair.target.dot(tangentAxis));
          const tangentOffset = (
            (Math.min(...targetTangent) + Math.max(...targetTangent))
            - (Math.min(...sourceTangent) + Math.max(...sourceTangent))
          ) / 2;
          tangentCorrection.set(
            tangentAxis.x * tangentOffset,
            tangentAxis.y * tangentOffset,
            tangentAxis.z * tangentOffset,
          );
        }
        const reflection = new THREE.Matrix4().set(
          1 - 2 * nx * nx, -2 * nx * ny, -2 * nx * nz, 0,
          -2 * ny * nx, 1 - 2 * ny * ny, -2 * ny * nz, 0,
          -2 * nz * nx, -2 * nz * ny, 1 - 2 * nz * nz, 0,
          0, 0, 0, 1,
        );
        runtime.modelGroup.matrix
          .makeTranslation(tangentCorrection.x, tangentCorrection.y, tangentCorrection.z)
          .multiply(new THREE.Matrix4().makeTranslation(center.x, center.y, center.z))
          .multiply(reflection)
          .multiply(new THREE.Matrix4().makeTranslation(-center.x, -center.y, -center.z));
      }
    }
    runtime.modelGroup.updateMatrixWorld(true);
  }, [mirrorModel, runtimeVersion, structuralElements]);

  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!runtime || runtimeVersion === 0) return;
    if (runtime.planOverlay) {
      runtime.scene.remove(runtime.planOverlay);
      runtime.planOverlay.geometry.dispose();
      const previousMaterial = runtime.planOverlay.material as THREE.MeshBasicMaterial;
      previousMaterial.map?.dispose();
      previousMaterial.dispose();
      runtime.planOverlay = null;
    }
    if (!runtime.planToBim || !planImageUrl) return;

    const planPoints = structuralElements.flatMap((element) => (
      element.geometry_json.footprint ?? element.geometry_json.line ?? []
    )).map((point) => [Number(point[0]), Number(point[1])] as const)
      .filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]));
    if (planPoints.length < 3) return;
    const padding = 0.035;
    const minX = Math.max(0, Math.min(...planPoints.map((point) => point[0])) - padding);
    const maxX = Math.min(1, Math.max(...planPoints.map((point) => point[0])) + padding);
    const minY = Math.max(0, Math.min(...planPoints.map((point) => point[1])) - padding);
    const maxY = Math.min(1, Math.max(...planPoints.map((point) => point[1])) + padding);
    const floorElevation = runtime.planToBim.cameraHeight - 1.57;
    const corners = [
      runtime.planToBim.map(minX, minY, floorElevation),
      runtime.planToBim.map(maxX, minY, floorElevation),
      runtime.planToBim.map(maxX, maxY, floorElevation),
      runtime.planToBim.map(minX, maxY, floorElevation),
    ];
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(corners.flatMap((point) => point.toArray()), 3));
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute([
      minX, 1 - minY,
      maxX, 1 - minY,
      maxX, 1 - maxY,
      minX, 1 - maxY,
    ], 2));
    geometry.setIndex([0, 1, 2, 0, 2, 3]);
    geometry.computeVertexNormals();

    let cancelled = false;
    let createdOverlay: THREE.Mesh | null = null;
    new THREE.TextureLoader().load(planImageUrl, (texture) => {
      if (cancelled || runtimeRef.current !== runtime) {
        texture.dispose();
        geometry.dispose();
        return;
      }
      texture.colorSpace = THREE.SRGBColorSpace;
      const material = new THREE.MeshBasicMaterial({
        map: texture,
        opacity: 0.3,
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
      });
      const overlay = new THREE.Mesh(geometry, material);
      overlay.renderOrder = -1;
      overlay.visible = viewMode === "inspect";
      createdOverlay = overlay;
      runtime.planOverlay = overlay;
      runtime.scene.add(overlay);
    });
    return () => {
      cancelled = true;
      if (!createdOverlay) return;
      runtime.scene.remove(createdOverlay);
      createdOverlay.geometry.dispose();
      const material = createdOverlay.material as THREE.MeshBasicMaterial;
      material.map?.dispose();
      material.dispose();
      if (runtime.planOverlay === createdOverlay) runtime.planOverlay = null;
    };
  }, [planImageUrl, runtimeVersion, structuralElements, viewMode]);

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

    const planToBim = runtime.planToBim;
    if (!planToBim) return;
    const routePositions: THREE.Vector3[] = [];
    const routeFrames: Keyframe[] = [];
    for (const frame of floorFrames) {
      const x = Number(frame.pose?.x);
      const y = Number(frame.pose?.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      const position = planToBim.map(x, y, planToBim.cameraHeight);
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

      const viewHeading = Number(activeFrame.pose.heading_deg) + panoramaView.longitude;
      const horizontalDirection = planToBim.direction(viewHeading);
      if (horizontalDirection) {
        const arrowLength = Math.max(Math.max(modelSize.x, modelSize.z) * 0.12, markerRadius * 5);
        const headingArrow = new THREE.ArrowHelper(
          horizontalDirection.normalize(),
          activePosition,
          arrowLength,
          0xff8a00,
          Math.max(arrowLength * 0.28, markerRadius * 2.4),
          Math.max(arrowLength * 0.16, markerRadius * 1.4),
        );
        (headingArrow.line.material as THREE.Material).depthTest = false;
        (headingArrow.cone.material as THREE.Material).depthTest = false;
        headingArrow.line.renderOrder = 13;
        headingArrow.cone.renderOrder = 13;
        runtime.headingArrow = headingArrow;
        runtime.pathLayer.add(headingArrow);
      }
    }
  }, [activeKeyframeId, keyframes, panoramaView.longitude, runtimeVersion]);

  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!runtime || runtimeVersion === 0) return;
    runtime.controls.enabled = viewMode !== "follow";
    runtime.pathLayer.visible = viewMode !== "follow";
    runtime.inspectionLight.visible = viewMode === "inspect";
    if (runtime.planOverlay) runtime.planOverlay.visible = viewMode === "inspect";
    if (!runtime.planToBim) return;
    const activeFrame = keyframes.find((frame) => frame.id === activeKeyframeId && frame.pose);
    const routePosition = activeFrame ? runtime.pathPositions.get(activeFrame.id) : null;
    if (!activeFrame?.pose || !routePosition) return;

    const modelSize = runtime.modelBounds.getSize(new THREE.Vector3());
    // Convert the complete plan heading through the registration. Rotating an
    // already-converted vector in Three.js reverses left/right when plan Y and
    // IFC Y use opposite screen handedness, which made the BIM look mirrored.
    const viewHeading = Number(activeFrame.pose.heading_deg) + panoramaView.longitude;
    const horizontalDirection = runtime.planToBim.direction(viewHeading);
    if (!horizontalDirection) return;
    const pitch = THREE.MathUtils.degToRad(panoramaView.latitude);
    const direction = horizontalDirection.clone().multiplyScalar(Math.cos(pitch));
    direction.y = Math.sin(pitch);
    direction.normalize();

    if (viewMode === "inspect") {
      runtime.mirrorFollowProjection = false;
      // Inspection is a plan-comparison view, so keep the BIM screen axes
      // identical to the drawing: plan +X is screen-right and plan +Y is
      // screen-down. An arbitrary isometric view made a correct transformed
      // route look reversed when it was compared with the 2D plan beside it.
      const planDown = runtime.planToBim.direction(90);
      if (!planDown) return;
      const overviewBounds = runtime.modelBounds.clone();
      for (const position of runtime.pathPositions.values()) overviewBounds.expandByPoint(position);
      const overviewCenter = overviewBounds.getCenter(new THREE.Vector3());
      const overviewSize = overviewBounds.getSize(new THREE.Vector3());
      const radius = Math.max(overviewSize.x, overviewSize.z, modelSize.y, 1);
      // The IFC-to-viewer conversion reverses its horizontal Z axis. Looking
      // along +Y from below compensates that handedness for this diagnostic
      // projection, so plan +X remains screen-right while plan +Y remains
      // screen-down. Materials are double-sided, therefore the structural
      // inspection drawing remains visible without mirroring model data.
      runtime.camera.position.copy(overviewCenter).add(new THREE.Vector3(0, -radius * 2.15, 0));
      runtime.camera.up.copy(planDown).multiplyScalar(-1).normalize();
      runtime.controls.target.copy(overviewCenter);
      runtime.camera.fov = 48;
      runtime.camera.near = Math.max(radius / 10000, 0.01);
      runtime.camera.far = Math.max(radius * 60, 100);
      updateBimProjection(runtime.camera);
      runtime.controls.update();
      return;
    }
    if (viewMode === "free") {
      runtime.mirrorFollowProjection = false;
      updateBimProjection(runtime.camera);
      return;
    }

    const cameraPosition = routePosition.clone();
    runtime.camera.position.copy(cameraPosition);
    runtime.camera.up.set(0, 1, 0);
    runtime.camera.lookAt(cameraPosition.clone().add(direction));
    runtime.camera.fov = THREE.MathUtils.clamp(panoramaView.fov, 35, 95);
    runtime.camera.near = Math.max(Math.max(modelSize.x, modelSize.y, modelSize.z) / 20000, 0.01);
    runtime.camera.far = Math.max(Math.max(modelSize.x, modelSize.y, modelSize.z) * 60, 100);
    runtime.mirrorFollowProjection = mirrorModel;
    updateBimProjection(runtime.camera, runtime.mirrorFollowProjection);
    runtime.camera.updateMatrixWorld(true);

    // The route and heading marker are useful in free BIM mode, but hiding the
    // layer while following the camera prevents the marker from filling the
    // first-person view and being mistaken for model geometry.
  }, [activeKeyframeId, keyframes, mirrorModel, panoramaView, runtimeVersion, viewMode]);

  return (
    <section className="bim-viewer-shell">
      <div className="bim-canvas" ref={containerRef} />
      <div className="bim-model-label">
        <span>BIM รุ่น {model.version_no}</span>
        <strong>{model.name}</strong>
      </div>
      {!error && loading.percent === 100 && (
        <nav className="bim-viewcube" aria-label="ViewCube และการนำทางโมเดลแบบ Revit">
          <button
            className="bim-viewcube-home"
            onClick={() => frameBimView(new THREE.Vector3(1, 0.72, 1))}
            title="กลับมุมมอง Home"
            type="button"
          >⌂</button>
          <div className="bim-viewcube-cube" ref={viewCubeRef} aria-label="เลือกด้านของโมเดล">
            <button
              className="is-top"
              onClick={() => frameBimView(new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, -1))}
              title="มุมมองด้านบน"
              type="button"
            >TOP</button>
            <button
              className="is-left"
              onClick={() => frameBimView(new THREE.Vector3(-1, 0, 0))}
              title="มุมมองด้านซ้าย"
              type="button"
            >LEFT</button>
            <button
              className="is-front"
              onClick={() => frameBimView(new THREE.Vector3(0, 0, 1))}
              title="มุมมองด้านหน้า"
              type="button"
            >FRONT</button>
            <button
              className="is-right"
              onClick={() => frameBimView(new THREE.Vector3(1, 0, 0))}
              title="มุมมองด้านขวา"
              type="button"
            >RIGHT</button>
            <button
              className="is-back"
              onClick={() => frameBimView(new THREE.Vector3(0, 0, -1))}
              title="มุมมองด้านหลัง"
              type="button"
            >BACK</button>
            <button
              className="is-bottom"
              onClick={() => frameBimView(new THREE.Vector3(0, -1, 0), new THREE.Vector3(0, 0, 1))}
              title="มุมมองด้านล่าง"
              type="button"
            >BOTTOM</button>
          </div>
          <div className="bim-viewcube-edges" aria-label="เลือกขอบ ViewCube">
            <button className="is-edge-back" onClick={() => frameBimView(new THREE.Vector3(0, 0, -1))} title="ขอบด้านหลัง" type="button">B</button>
            <button className="is-edge-left" onClick={() => frameBimView(new THREE.Vector3(-1, 0, 0))} title="ขอบด้านซ้าย" type="button">L</button>
            <button className="is-edge-right" onClick={() => frameBimView(new THREE.Vector3(1, 0, 0))} title="ขอบด้านขวา" type="button">R</button>
            <button className="is-edge-front" onClick={() => frameBimView(new THREE.Vector3(0, 0, 1))} title="ขอบด้านหน้า" type="button">F</button>
          </div>
          <div className="bim-viewcube-ring" aria-label="หมุนมุมมองทีละ 90 องศา">
            <button onClick={() => rotateBimQuarterTurn(-1)} title="หมุนซ้าย 90°" type="button">↶</button>
            <span>N</span>
            <button onClick={() => rotateBimQuarterTurn(1)} title="หมุนขวา 90°" type="button">↷</button>
          </div>
        </nav>
      )}
      {!error && loading.percent === 100 && (
        <div className="bim-sync-toolbar">
          <div className="bim-view-mode-buttons" role="group" aria-label="โหมดมุมมอง BIM">
            <button
              className={viewMode === "follow" ? "is-active" : ""}
              disabled={!registration}
              onClick={() => setViewMode("follow")}
              type="button"
            >ตามภาพ 360°</button>
            <button
              className={viewMode === "inspect" ? "is-active" : ""}
              disabled={!registration}
              onClick={() => setViewMode("inspect")}
              type="button"
            >ตรวจตำแหน่ง</button>
            <button
              className={viewMode === "free" ? "is-active" : ""}
              onClick={() => setViewMode("free")}
              type="button"
            >ดูโมเดลอิสระ</button>
          </div>
          {viewMode === "free" && savedViewpoint?.keyframe_id === activeKeyframeId && (
            <button onClick={() => applySavedViewpoint()} type="button">ใช้มุมที่บันทึก</button>
          )}
          {viewMode === "free" && canSaveViewpoint && activeKeyframeId && viewpointApiAvailable && (
            <button disabled={viewpointStatus === "saving"} onClick={saveCurrentViewpoint} type="button">
              {viewpointStatus === "saving" ? "กำลังบันทึก…" : viewpointStatus === "saved" ? "บันทึกแล้ว" : "บันทึกมุมจุดนี้"}
            </button>
          )}
          {registration
            ? <span><i /> แปลน↔IFC {registration.matchedElementCount} จุด · คลาดเคลื่อน {registration.rmsErrorMeters.toFixed(2)} ม.</span>
            : <span className="is-warning">ไม่แสดงตำแหน่งกล้อง เพราะยังจับคู่ IFC กับแปลนไม่ได้</span>}
        </div>
      )}
      {!error && loading.percent === 100 && (
        <div className="bim-category-toolbar" aria-label="ตัวกรองหมวด BIM">
          <strong>แสดงโมเดล</strong>
          <button
            aria-pressed={mirrorModel}
            className={mirrorModel ? "is-active" : ""}
            onClick={() => setMirrorModel((current) => !current)}
            type="button"
          >Mirror IFC บน↕ล่าง</button>
          {BIM_CATEGORIES.map((category) => categoryCounts[category.key] > 0 && (
            <button
              aria-pressed={visibleCategories[category.key]}
              className={visibleCategories[category.key] ? "is-active" : ""}
              key={category.key}
              onClick={() => setVisibleCategories((current) => ({
                ...current,
                [category.key]: !current[category.key],
              }))}
              type="button"
            >
              {category.label}
            </button>
          ))}
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
          {!registration
            ? "หมุนและซูมดูโมเดลได้ แต่ระบบจะไม่วางกล้องหรือเส้นทางด้วยค่าประมาณ"
            : viewMode === "follow"
            ? "BIM อยู่ที่ Camera Pose และหันตามภาพ 360° แบบเรียลไทม์"
            : viewMode === "inspect"
            ? "เส้นทางอยู่นิ่ง · ล้อกลาง Pan · Shift+ล้อกลาง Orbit · หมุนล้อ Zoom"
            : "แบบ Revit: ล้อกลางลากเพื่อ Pan · Shift+ล้อกลางลากเพื่อ Orbit · หมุนล้อเพื่อ Zoom"}
        </div>
      )}
    </section>
  );
}
