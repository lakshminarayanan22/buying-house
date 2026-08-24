"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { ApiError, api } from "@/lib/api";
import { PageHeader } from "@/components/AppShell";
import { TaxonomyPicker } from "@/components/TaxonomyPicker";
import { Alert, Button, Card, CardHeader, Field, Input } from "@/components/ui";
import type { Organization } from "@/lib/types";

/**
 * Tier 1 — Registered. Eight fields, five minutes (§5.2).
 *
 * It deliberately does not ask for GST, capacity, MOQ, machinery or certificates. Those are
 * Tier 2, and asking for them here is how you lose a factory owner at field nine. Everything
 * omitted can be added later, from a phone, over a resumable link.
 */
export default function RegisterSupplier() {
  const router = useRouter();
  const [form, setForm] = React.useState({
    factory_name: "",
    city: "",
    country_code: "IN",
    primary_process_code: "",
    primary_category_code: "",
    contact_name: "",
    phone: "",
    whatsapp: "",
    language_pref: "en",
  });
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  function set<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const org = await api.post<Organization>("/suppliers/register", {
        ...form,
        whatsapp: form.whatsapp || undefined,
      });
      router.push(`/internal/suppliers/${org.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not register this supplier.");
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Register a supplier"
        subtitle="Eight fields. Capacity, certificates and machinery come later — this just gets them in."
      />

      <form onSubmit={submit} className="max-w-2xl">
        <Card>
          <CardHeader title="The factory" />
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Field label="Factory name" required>
                <Input
                  value={form.factory_name}
                  onChange={(e) => set("factory_name", e.target.value)}
                  placeholder="Kovai Knits Pvt Ltd"
                  required
                />
              </Field>
            </div>
            <Field label="City" required>
              <Input
                value={form.city}
                onChange={(e) => set("city", e.target.value)}
                placeholder="Tiruppur"
                required
              />
            </Field>
            <Field label="Country" required>
              <TaxonomyPicker
                domain="COUNTRY"
                value={form.country_code}
                onChange={(code) => set("country_code", code)}
                required
              />
            </Field>
            <Field
              label="Main process"
              hint="Type what they call it — 'sinker', 'process house' and 'CMT' all resolve"
              required
            >
              <TaxonomyPicker
                domain="PROCESS_TYPE"
                value={form.primary_process_code}
                onChange={(code) => set("primary_process_code", code)}
                required
              />
            </Field>
            <Field label="Main product" required>
              <TaxonomyPicker
                domain="PRODUCT_CATEGORY"
                value={form.primary_category_code}
                onChange={(code) => set("primary_category_code", code)}
                required
              />
            </Field>
          </div>

          <CardHeader title="Who we talk to" />
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            <Field label="Contact person" required>
              <Input
                value={form.contact_name}
                onChange={(e) => set("contact_name", e.target.value)}
                placeholder="R. Murugan"
                required
              />
            </Field>
            <Field label="Phone" required>
              <Input
                type="tel"
                value={form.phone}
                onChange={(e) => set("phone", e.target.value)}
                placeholder="+91 90000 00000"
                required
              />
            </Field>
            <Field label="WhatsApp" hint="Leave blank if it is the same number — usually it is">
              <Input
                type="tel"
                value={form.whatsapp}
                onChange={(e) => set("whatsapp", e.target.value)}
                placeholder="Same as phone"
              />
            </Field>
            <Field label="Preferred language" hint="Notifications and their own portal use this">
              <select
                className="w-full rounded-md border px-2.5 py-1.5 text-sm"
                style={{
                  background: "var(--surface)",
                  borderColor: "var(--border-strong)",
                  color: "var(--text)",
                }}
                value={form.language_pref}
                onChange={(e) => set("language_pref", e.target.value)}
              >
                <option value="en">English</option>
                <option value="ta">தமிழ் (Tamil)</option>
              </select>
            </Field>
          </div>

          {error ? (
            <div className="px-5 pb-4">
              <Alert>{error}</Alert>
            </div>
          ) : null}

          <div
            className="flex items-center justify-between gap-3 border-t px-5 py-3"
            style={{ borderColor: "var(--border)" }}
          >
            <p className="text-xs" style={{ color: "var(--text-subtle)" }}>
              Recorded as entered by our team, not self-reported by the factory.
            </p>
            <div className="flex gap-2">
              <Button type="button" onClick={() => router.back()}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" loading={busy}>
                Register
              </Button>
            </div>
          </div>
        </Card>
      </form>
    </>
  );
}
