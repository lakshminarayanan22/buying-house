// Mirrors the FastAPI response models. Kept hand-written and small rather than generated:
// the surface the UI actually consumes is much narrower than the OpenAPI schema.

export type Side = "INTERNAL" | "BRAND" | "SUPPLIER";

export type Role =
  | "INTERNAL_SUPER_ADMIN"
  | "INTERNAL_MANAGEMENT"
  | "INTERNAL_SOURCING_HEAD"
  | "INTERNAL_MERCHANDISER"
  | "INTERNAL_QA"
  | "BRAND_ADMIN"
  | "BRAND_USER"
  | "SUPPLIER_ADMIN"
  | "SUPPLIER_USER";

export type OrgStatus =
  | "INVITED"
  | "DRAFT"
  | "SUBMITTED"
  | "UNDER_REVIEW"
  | "NEEDS_INFO"
  | "VERIFIED"
  | "REJECTED"
  | "SUSPENDED";

export type SupplierTier =
  | "TIER_1_REGISTERED"
  | "TIER_2_PROFILED"
  | "TIER_3_VERIFIED";

export type DataSource = "SELF_REPORTED" | "INTERNAL_VERIFIED" | "OBSERVED";

export interface CurrentUser {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: Role;
  side: Side;
  org_id: string | null;
  org_name: string | null;
  org_status: OrgStatus | null;
  language_pref: string;
  portals: string[];
}

export interface Organization {
  id: string;
  type: "BRAND" | "SUPPLIER";
  legal_name: string;
  trade_name: string | null;
  country_id: string | null;
  state: string | null;
  city: string | null;
  status: OrgStatus;
  website: string | null;
  year_established: number | null;
  employee_count: number | null;
  created_by_internal: boolean;
  created_at: string;
}

export interface ReferenceItem {
  id: string;
  domain: string;
  code: string;
  name: string;
  description: string | null;
  parent_id: string | null;
  path: string;
  depth: number;
  sort_order: number;
  is_active: boolean;
  aliases?: string[];
}

export interface UnmappedTerm {
  id: string;
  domain: string;
  raw_text: string;
  normalised: string;
  occurrences: number;
  source_entity_type: string | null;
  resolved_item_id: string | null;
}

/** A directory row. Identity fields are absent unless `is_identity_visible`. */
export interface DirectorySupplier {
  id: string;
  legal_name?: string;
  trade_name?: string | null;
  website?: string | null;
  masked_ref?: string;
  city: string | null;
  state: string | null;
  status: OrgStatus;
  processes: string[];
  categories: string[];
  certifications: string[];
  completeness_pct: number;
  tier: SupplierTier | null;
  is_identity_visible: boolean;
}

export interface SupplierProcess {
  id: string;
  process_type_id: string;
  is_inhouse: boolean;
  is_subcontracted: boolean;
  monthly_capacity_value: number | null;
  capacity_uom: string | null;
  min_order_qty: number | null;
  moq_uom: string | null;
  standard_lead_time_days: number | null;
  sample_lead_time_days: number | null;
  source: DataSource;
}

export interface SupplierCapability {
  id: string;
  product_category_id: string;
  gsm_min: number | null;
  gsm_max: number | null;
  size_range: string | null;
  price_band_min: number | null;
  price_band_max: number | null;
  currency_id: string | null;
  notes: string | null;
  source: DataSource;
}

export interface Certification {
  id: string;
  certification_id: string;
  certificate_no: string | null;
  issuing_body: string | null;
  issued_on: string | null;
  valid_till: string | null;
  verification_status: "PENDING" | "VERIFIED" | "REJECTED" | "EXPIRED";
  source: DataSource;
}

export interface Completeness {
  completeness_pct: number;
  tier: SupplierTier;
  missing: string[];
  checks: Record<string, boolean>;
}

export interface SupplierProfile {
  org_id: string;
  completeness_tier: SupplierTier;
  completeness_pct: number;
  export_experience_years: number | null;
  annual_turnover_band: string | null;
  is_vertically_integrated: boolean;
  capability_narrative: string | null;
  source: DataSource;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ChangeCell {
  before: unknown;
  after: unknown;
}

export interface ChangeRow {
  pk: string[];
  operation: "INSERT" | "UPDATE" | "DELETE";
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  changes: Record<string, ChangeCell>;
}

export interface ChangePreview {
  id: string;
  prompt: string;
  generated_sql: string;
  explanation: string | null;
  target_table: string;
  statement_kind: "INSERT" | "UPDATE" | "DELETE";
  affected_count: number;
  diff: ChangeRow[] | null;
  status: string;
  planner_backend: string;
  planner_model: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface FacetValue {
  code: string;
  name: string;
  count: number;
}
