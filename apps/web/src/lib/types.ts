export type User = {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  created_at: string;
};

export type Project = {
  id: string;
  name: string;
  location: string | null;
  timezone: string;
  description: string | null;
  structural_tracking_end_date: string | null;
  created_by_id: string;
  created_at: string;
  updated_at: string;
  role: "admin" | "sub_admin" | "reviewer" | "viewer" | null;
};

export type ProjectMember = {
  id: string;
  user_id: string;
  email: string;
  display_name: string;
  role: "admin" | "sub_admin" | "reviewer" | "viewer";
  created_at: string;
};

export type FieldNoteStatus = "OPEN" | "P1" | "P2" | "P3" | "COMPLETED" | "VERIFIED";

export type FieldNote = {
  id: string;
  project_id: string;
  capture_id: string;
  capture_date: string;
  floor_id: string;
  floor_name: string;
  keyframe_id: string;
  keyframe_timestamp_ms: number;
  image_url: string;
  title: string;
  description: string | null;
  status: FieldNoteStatus;
  due_date: string | null;
  tags: string[];
  markup_paths: Array<Array<[number, number]>>;
  assignee_id: string | null;
  assignee_name: string | null;
  plan_x: number | null;
  plan_y: number | null;
  panorama_longitude: number;
  panorama_latitude: number;
  panorama_fov: number;
  created_by_id: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  comments: Array<{
    id: string;
    body: string;
    created_by_id: string;
    created_by_name: string;
    created_at: string;
  }>;
  attachments: Array<{
    id: string;
    filename: string;
    content_type: string;
    size_bytes: number;
    download_url: string;
  }>;
};

export type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
};

export type ScheduleVersion = {
  id: string;
  project_id: string;
  name: string;
  version_no: number;
  source_type: string;
  is_baseline: boolean;
  imported_by_id: string;
  imported_at: string;
  row_count: number;
  checksum: string;
  status: string;
};

export type Activity = {
  id: string;
  schedule_version_id: string;
  parent_activity_id: string | null;
  wbs: string;
  name: string;
  planned_start: string;
  planned_finish: string;
  is_summary: boolean;
  source_row_no: number;
  created_at: string;
};

export type SchedulePreview = {
  filename: string;
  checksum: string;
  sheet_name: string;
  row_count: number;
  used_baseline_dates: boolean;
  warnings: string[];
  activities: Array<Omit<Activity, "id" | "schedule_version_id" | "parent_activity_id" | "created_at"> & {
    parent_wbs: string | null;
  }>;
};

export type HumanProgressEntry = {
  id: string;
  project_id: string;
  activity_id: string;
  activity_wbs: string | null;
  capture_id: string | null;
  observed_at: string;
  progress_percent: string;
  note: string | null;
  entered_by_id: string;
  created_at: string;
};

export type ProgressComparisonItem = {
  activity_id: string;
  wbs: string;
  name: string;
  planned_percent: string;
  human_actual_percent: string | null;
  human_observed_at: string | null;
  variance_pp: string | null;
};

export type ProgressComparison = {
  project_id: string;
  capture_id: string;
  capture_date: string;
  schedule_version_id: string;
  schedule_name: string;
  items: ProgressComparisonItem[];
};

export type Floor = {
  id: string;
  project_id: string;
  name: string;
  level_index: number;
  elevation_m: string | null;
  available_from: string | null;
  has_plan: boolean;
  created_at: string;
  updated_at: string;
};

export type FloorPlanInfo = {
  filename: string | null;
  content_type: string;
  page_number: number;
  page_count: number;
  width_px: number | null;
  height_px: number | null;
};

export type Capture = {
  id: string;
  project_id: string;
  source_video_id: string;
  captured_at: string;
  captured_by_text: string | null;
  start_floor_id: string;
  start_x: string;
  start_y: string;
  notes: string | null;
  dataset_split: "DEVELOPMENT" | "HOLDOUT_TEST";
  status: string;
  created_by_id: string;
  created_at: string;
  updated_at: string;
};

export type MediaFile = {
  id: string;
  project_id: string;
  media_kind: string;
  bucket: string;
  object_key: string;
  original_filename: string | null;
  content_type: string;
  size_bytes: number;
  checksum_sha256: string | null;
  upload_status: string;
  created_by_id: string | null;
  created_at: string;
};

export type BimModel = {
  id: string;
  project_id: string;
  name: string;
  version_no: number;
  ifc_schema: string;
  size_bytes: number;
  download_url: string;
  created_by_id: string | null;
  created_at: string;
};

export type BimModelList = {
  active: BimModel | null;
  versions: BimModel[];
};

export type BimViewpoint = {
  id: string;
  project_id: string;
  model_media_file_id: string;
  keyframe_id: string;
  position_x: number;
  position_y: number;
  position_z: number;
  target_x: number;
  target_y: number;
  target_z: number;
  fov: number;
  updated_by_id: string;
  created_at: string;
  updated_at: string;
};

export type MultipartInitiate = {
  media: MediaFile;
  upload_session_id: string;
  part_size_bytes: number;
  part_count: number;
  expires_at: string;
};

export type MultipartStatus = {
  media_id: string;
  original_filename: string | null;
  size_bytes: number;
  upload_session_id: string;
  status: string;
  part_size_bytes: number;
  part_count: number;
  expires_at: string;
  uploaded_parts: Array<{ part_number: number; etag: string; size_bytes: number }>;
  upload_urls: Array<{ part_number: number; url: string }>;
};

export type MultipartComplete = {
  media: MediaFile;
  capture_id: string;
  capture_status: string;
  processing_job_id: string;
};

export type StorageStatus = {
  provider: string;
  project_object_bytes: number;
  disk_total_bytes: number | null;
  disk_free_bytes: number | null;
  minimum_free_bytes: number;
  upload_allowed: boolean;
  guard_path: string | null;
  message: string;
};

export type ProcessingJob = {
  id: string;
  capture_id: string;
  job_type: string;
  status: string;
  progress_percent: string;
  attempt_no: number;
  pipeline_version: string;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
};

export type CaptureDetail = {
  capture: Capture;
  metadata: null | {
    duration_ms: number;
    width_px: number;
    height_px: number;
    fps: string;
    codec_name: string;
    is_equirectangular: boolean;
  };
  proxy_url: string | null;
  keyframes: Array<{
    id: string;
    frame_index: number;
    timestamp_ms: number;
    quality_status: string;
    is_warp_point: boolean;
    image_url: string;
    pose: null | {
      id: string;
      keyframe_id: string;
      floor_id: string;
      x: string;
      y: string;
      heading_deg: string;
      visual_x: string | null;
      visual_y: string | null;
      visual_heading_deg: string | null;
      visual_z: string | null;
      visual_ground_z: string | null;
      orientation_qx: string | null;
      orientation_qy: string | null;
      orientation_qz: string | null;
      orientation_qw: string | null;
      relative_z_m: string | null;
      confidence: string;
      localization_run_id: string;
      algorithm: string;
      needs_review: boolean;
      reviewed_by_id: string | null;
      reviewed_at: string | null;
      created_at: string;
      updated_at: string;
    };
  }>;
  route_vectors: Array<{
    from_keyframe_id: string;
    to_keyframe_id: string;
    delta_x: number;
    delta_y: number;
    delta_z: number;
    distance: number;
    bearing_deg: number;
    local_yaw_deg: number;
    local_pitch_deg: number;
    direction_source: string;
    confidence: number;
    verified: boolean;
    verification_method: string;
  }>;
  path_points: Array<{
    id: string;
    floor_id: string;
    timestamp_ms: number;
    x: string;
    y: string;
    heading_deg: string;
    confidence: string;
    localization_run_id: string;
    algorithm: string;
  }>;
  control_points: Array<{
    id: string;
    capture_id: string;
    keyframe_id: string;
    floor_id: string;
    x: string;
    y: string;
    error_normalized: string;
    created_by_id: string;
    created_at: string;
  }>;
  evaluation_points: Array<{
    id: string;
    capture_id: string;
    keyframe_id: string;
    floor_id: string;
    localization_run_id: string;
    target_x: string;
    target_y: string;
    predicted_x: string;
    predicted_y: string;
    error_normalized: string;
    tolerance_normalized: string;
    is_within_tolerance: boolean;
    created_by_id: string;
    created_at: string;
  }>;
  evaluation_summary: null | {
    point_count: number;
    required_point_count: number;
    is_ready: boolean;
    tolerance_normalized: string;
    within_tolerance_count: number;
    accuracy_percent: string;
    rmse_normalized: string;
    max_error_normalized: string;
  };
  jobs: ProcessingJob[];
};

export type BeamSegment = {
  id: string;
  sheet_id: string;
  code: string;
  beam_type: string | null;
  start_x: string;
  start_y: string;
  end_x: string;
  end_y: string;
  length_m: string | null;
  source: string;
  is_active: boolean;
};

export type StructuralElement = {
  id: string;
  project_id: string;
  floor_id: string | null;
  sheet_id: string | null;
  ifc_global_id: string;
  ifc_type: string;
  ifc_storey: string | null;
  element_kind: "BEAM" | "COLUMN" | "SLAB" | "STAIR" | "FOUNDATION" | "PEDESTAL" | "ROOF";
  code: string;
  name: string | null;
  geometry_json: {
    line?: [[number, number], [number, number]];
    lines?: Array<[[number, number], [number, number]]>;
    footprint?: Array<[number, number]>;
    activity_wbs?: string;
    progress_mode?: "COUNT";
    total_quantity?: number;
  };
  source: string;
  is_active: boolean;
};

export type BeamProgress = {
  project_id: string;
  capture_id: string;
  floor_id: string;
  labeled_count: number;
  segment_count: number;
  weighted_progress_percent: string | null;
  total_length_m: string;
  completed_equivalent_length_m: string;
  items: Array<{
    beam_segment_id: string;
    code: string;
    beam_type: string | null;
    start_x: string;
    start_y: string;
    end_x: string;
    end_y: string;
    length_m: string | null;
    progress_percent: string | null;
    completed_stages: Array<"SETTING_OUT" | "SHORING" | "REBAR" | "FORMWORK" | "CONCRETE" | "STRIP_FORM">;
    stage_ranges: Partial<Record<"SETTING_OUT" | "SHORING" | "REBAR" | "FORMWORK" | "CONCRETE" | "STRIP_FORM", Array<{
      start_m: string;
      end_m: string;
    }>>>;
    evidence_keyframe_id: string | null;
    note: string | null;
    entered_by_id: string | null;
    created_at: string | null;
  }>;
  stage_summaries: Array<{
    stage: "SETTING_OUT" | "SHORING" | "REBAR" | "FORMWORK" | "CONCRETE" | "STRIP_FORM";
    completed_length_m: string;
    total_length_m: string;
    progress_percent: string;
  }>;
};

export type ColumnStageCode = "REBAR" | "FORMWORK" | "CONCRETE" | "STRIP_FORM";

export type ColumnProgress = {
  project_id: string;
  capture_id: string;
  floor_id: string;
  labeled_count: number;
  column_count: number;
  progress_percent: string;
  stage_summaries: Array<{
    stage: ColumnStageCode;
    completed_count: number;
    total_count: number;
    progress_percent: string;
  }>;
  items: Array<{
    structural_element_id: string;
    code: string;
    grid_label: string;
    geometry_json: {
      footprint?: Array<[number, number]>;
    };
    progress_percent: string | null;
    completed_stages: ColumnStageCode[];
    evidence_keyframe_id: string | null;
    note: string | null;
    entered_by_id: string | null;
    created_at: string | null;
  }>;
};

export type StairStageCode = "SHORING" | "REBAR" | "FORMWORK" | "CONCRETE" | "STRIP_FORM";

export type StairProgress = {
  project_id: string;
  capture_id: string;
  floor_id: string;
  labeled_count: number;
  stair_count: number;
  progress_percent: string;
  stage_summaries: Array<{
    stage: StairStageCode;
    completed_count: number;
    total_count: number;
    progress_percent: string;
  }>;
  items: Array<{
    structural_element_id: string;
    code: string;
    geometry_json: { footprint?: Array<[number, number]> };
    progress_percent: string | null;
    completed_stages: StairStageCode[];
    evidence_keyframe_id: string | null;
    note: string | null;
    entered_by_id: string | null;
    created_at: string | null;
  }>;
};

export type SlabStageCode =
  | "STEP_1" | "STEP_2" | "STEP_3" | "STEP_4" | "STEP_5"
  | "SHORING" | "PLACE_PRECAST" | "SOIL_COMPACTION"
  | "REBAR" | "FORMWORK" | "CONCRETE" | "STRIP_FORM";

export type SlabProgress = {
  project_id: string;
  capture_id: string;
  floor_id: string;
  labeled_count: number;
  zone_count: number;
  total_area_m2: string;
  progress_percent: string;
  stage_summaries: Array<{
    stage: SlabStageCode;
    completed_area_m2: string;
    total_area_m2: string;
    progress_percent: string;
  }>;
  items: Array<{
    structural_element_id: string;
    code: string;
    area_m2: string;
    geometry_json: {
      footprint?: Array<[number, number]>;
      slab_type?: "GS" | "S1" | "PC1";
      slab_workflow?: "GS" | "S1_FLOOR_1" | "S1" | "PC1";
    };
    progress_percent: string | null;
    completed_stages: SlabStageCode[];
    evidence_keyframe_id: string | null;
    note: string | null;
    entered_by_id: string | null;
    created_at: string | null;
  }>;
};

export type RoofProgress = {
  project_id: string;
  capture_id: string;
  floor_id: string;
  labeled_count: number;
  element_count: number;
  progress_percent: string;
  items: Array<{
    structural_element_id: string;
    code: string;
    activity_wbs: string;
    geometry_json: {
      line?: [[number, number], [number, number]];
      lines?: Array<[[number, number], [number, number]]>;
      footprint?: Array<[number, number]>;
      activity_wbs?: string;
      progress_mode?: "COUNT";
      total_quantity?: number;
    };
    progress_percent: string | null;
    complete: boolean;
    completed_quantity: number | null;
    total_quantity: number | null;
    capture_id: string | null;
    evidence_keyframe_id: string | null;
    note: string | null;
    entered_by_id: string | null;
    created_at: string | null;
  }>;
};

export type WorkProgress = {
  project_id: string;
  capture_id: string;
  floor_id: string;
  labeled_count: number;
  item_count: number;
  human_progress_percent: string | null;
  items: Array<{
    work_item_id: string;
    code: string;
    discipline: "STRUCTURAL" | "ARCHITECTURAL";
    name: string;
    unit: string;
    weight: string;
    sequence: number;
    progress_percent: string | null;
    evidence_keyframe_id: string | null;
    note: string | null;
  }>;
};
