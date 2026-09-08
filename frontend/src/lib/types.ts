// Mirrors the FastAPI response models.

export type UserRole = "ADMIN" | "MEMBER";
export type CompanyStatus = "LEAD" | "ACTIVE" | "INACTIVE" | "BLACKLISTED";
export type DealRole = "BUYER" | "SUPPLIER" | "PROCESSOR" | "INPUT_SUPPLIER" | "OTHER";
export type DealStatus =
  | "LEAD" | "NEGOTIATING" | "AGREED" | "IN_PROGRESS"
  | "SHIPPED" | "COMPLETED" | "ON_HOLD" | "LOST";
export type CommissionBasis = "PERCENTAGE" | "MARGIN" | "FIXED" | "NONE";
export type CommissionStatus = "NOT_DUE" | "DUE" | "INVOICED" | "RECEIVED" | "WRITTEN_OFF";
export type MilestoneStatus = "PENDING" | "IN_PROGRESS" | "DONE" | "BLOCKED" | "SKIPPED";

export interface Me {
  id: string;
  name: string;
  email: string;
  role: UserRole;
}

export interface Ref {
  id: string;
  domain: string;
  code: string;
  name: string;
  aliases: string[];
  parent_id: string | null;
}

export interface Contact {
  id: string;
  name: string;
  designation: string | null;
  email: string | null;
  phone: string | null;
  whatsapp: string | null;
  is_primary: boolean;
}

export interface CompanyRow {
  id: string;
  name: string;
  city: string | null;
  country_id: string | null;
  buys: boolean;
  sells: boolean;
  status: CompanyStatus;
  processes: string[];
  products: string[];
  certifications: string[];
  has_brochure: boolean;
}

export interface CompanyDetail extends CompanyRow {
  legal_name: string | null;
  address: string | null;
  website: string | null;
  tax_id: string | null;
  payment_terms: string | null;
  quality_requirements: string | null;
  capacity_notes: string | null;
  machinery_notes: string | null;
  moq_notes: string | null;
  lead_time_notes: string | null;
  notes: string | null;
  contacts: Contact[];
  clients: string[];
  open_deals: number;
}

export interface Party {
  id: string;
  company_id: string;
  company_name: string | null;
  role: DealRole;
  process_name: string | null;
  sequence: number;
  qty: number | null;
  uom: string | null;
  unit_price: number | null;
  resale_unit_price: number | null;
  value: number | null;
  commission_basis: CommissionBasis;
  commission_pct: number | null;
  commission_amount: number | null;
  commission_status: CommissionStatus;
  invoiced_on: string | null;
  received_on: string | null;
  ship_date: string | null;
  notes: string | null;
}

export interface Milestone {
  id: string;
  name: string;
  sequence: number;
  planned_date: string | null;
  actual_date: string | null;
  status: MilestoneStatus;
  notes: string | null;
  is_overdue: boolean;
}

export interface DocRow {
  id: string;
  kind: string;
  title: string;
  original_filename: string | null;
  size_bytes: number | null;
  created_at: string;
}

export interface DealRow {
  id: string;
  deal_no: string;
  title: string;
  status: DealStatus;
  target_ship_date: string | null;
  last_activity_at: string | null;
  value: number;
  commission: number;
  party_count: number;
  counterparties: string[];
}

export interface DealDetail extends DealRow {
  description: string | null;
  notes: string | null;
  lost_reason: string | null;
  product_name: string | null;
  currency_code: string | null;
  incoterm_code: string | null;
  parties: Party[];
  milestones: Milestone[];
  documents: DocRow[];
}

export interface Dashboard {
  shipping: Array<{
    ship_date: string; deal_no: string; title: string; company: string;
    process: string | null; role: string; value: number;
    qty: number | null; uom: string | null; days_out: number; overdue: boolean;
  }>;
  commission: {
    outstanding: number;
    received: number;
    by_company: Array<{
      company_id: string; company: string; legs: number; amount: number;
      oldest_invoice: string | null; days_outstanding: number | null;
    }>;
  };
  quiet: Array<{
    deal_id: string; deal_no: string; title: string; status: DealStatus;
    last_activity: string; days_silent: number; target_ship_date: string | null;
  }>;
  milestones: Array<{
    planned_date: string | null; milestone: string; status: MilestoneStatus;
    deal_no: string; title: string; overdue: boolean;
  }>;
  pipeline: Array<{ status: DealStatus; deals: number; value: number; commission: number }>;
}
