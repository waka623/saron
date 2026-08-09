export type CampaignType = "birthday" | "no_visit_reminder" | "custom";

// Row shapes use `type` rather than `interface`: TypeScript only synthesizes
// the implicit index signature that `Record<string, GenericTable>` (used by
// @supabase/postgrest-js's generic constraints) needs during conditional
// `extends` checks for object-literal type aliases, not for interfaces. An
// interface here silently makes every query resolve to `never`.
export type Salon = {
  id: string;
  owner_id: string;
  name: string;
  line_channel_id: string | null;
  line_channel_secret: string | null;
  line_channel_access_token: string | null;
  created_at: string;
};

export type Staff = {
  id: string;
  salon_id: string;
  name: string;
  role: string | null;
  created_at: string;
};

export type Customer = {
  id: string;
  salon_id: string;
  name: string;
  phone: string | null;
  line_user_id: string | null;
  line_link_token: string;
  birthday: string | null;
  notes: string | null;
  created_at: string;
};

export type VisitRecord = {
  id: string;
  customer_id: string;
  salon_id: string;
  staff_id: string | null;
  visit_date: string;
  menu: string | null;
  memo: string | null;
  photo_urls: string[];
  created_at: string;
};

export type Campaign = {
  id: string;
  salon_id: string;
  name: string;
  type: CampaignType;
  days_since_last_visit: number | null;
  message_template: string;
  is_active: boolean;
  created_at: string;
};

export type CampaignLog = {
  id: string;
  campaign_id: string;
  customer_id: string;
  sent_at: string;
  status: "sent" | "failed" | "skipped";
  error_message: string | null;
};

/** Row fields with a database default (id, created_at, ...) are optional on insert. */
type Insertable<Row, Required extends keyof Row> = Pick<Row, Required> &
  Partial<Omit<Row, Required>>;

type Relationship = {
  foreignKeyName: string;
  columns: string[];
  isOneToOne?: boolean;
  referencedRelation: string;
  referencedColumns: string[];
};

type Table<Row, InsertRequired extends keyof Row, Relationships extends Relationship[] = []> = {
  Row: Row;
  Insert: Insertable<Row, InsertRequired>;
  Update: Partial<Row>;
  Relationships: Relationships;
};

export type Database = {
  public: {
    Tables: {
      salons: Table<Salon, "owner_id" | "name">;
      staff: Table<Staff, "salon_id" | "name">;
      customers: Table<Customer, "salon_id" | "name">;
      visit_records: Table<
        VisitRecord,
        "customer_id" | "salon_id",
        [
          {
            foreignKeyName: "visit_records_customer_id_fkey";
            columns: ["customer_id"];
            isOneToOne: false;
            referencedRelation: "customers";
            referencedColumns: ["id"];
          },
          {
            foreignKeyName: "visit_records_staff_id_fkey";
            columns: ["staff_id"];
            isOneToOne: false;
            referencedRelation: "staff";
            referencedColumns: ["id"];
          },
        ]
      >;
      campaigns: Table<Campaign, "salon_id" | "name" | "type" | "message_template">;
      campaign_logs: Table<
        CampaignLog,
        "campaign_id" | "customer_id" | "status",
        [
          {
            foreignKeyName: "campaign_logs_campaign_id_fkey";
            columns: ["campaign_id"];
            isOneToOne: false;
            referencedRelation: "campaigns";
            referencedColumns: ["id"];
          },
          {
            foreignKeyName: "campaign_logs_customer_id_fkey";
            columns: ["customer_id"];
            isOneToOne: false;
            referencedRelation: "customers";
            referencedColumns: ["id"];
          },
        ]
      >;
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
  };
};
