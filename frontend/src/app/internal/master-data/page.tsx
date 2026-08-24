"use client";

import * as React from "react";

import { ApiError, api } from "@/lib/api";
import { useAsync, useDebounced } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/AppShell";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Input,
  Select,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { titleCase } from "@/lib/format";
import type { Page, ReferenceItem, UnmappedTerm } from "@/lib/types";

const DOMAINS = [
  "PROCESS_TYPE",
  "PRODUCT_CATEGORY",
  "FIBRE",
  "FABRIC_CONSTRUCTION",
  "FINISH_TYPE",
  "CERTIFICATION",
  "COMPLIANCE_AUDIT_TYPE",
  "MACHINERY_TYPE",
  "COUNTRY",
  "PORT",
  "CURRENCY",
  "INCOTERM",
  "UOM",
];

export default function MasterData() {
  const { user } = useSession();
  const canEdit = user?.role === "INTERNAL_SUPER_ADMIN";

  const [domain, setDomain] = React.useState("PROCESS_TYPE");
  const [search, setSearch] = React.useState("");
  const debounced = useDebounced(search);
  const [banner, setBanner] = React.useState<string | null>(null);

  const items = useAsync(
    () =>
      api.get<ReferenceItem[]>("/master-data/items", {
        domain,
        search: debounced || undefined,
        include_inactive: true,
      }),
    [domain, debounced],
  );
  const unmapped = useAsync(
    () => api.get<Page<UnmappedTerm>>("/master-data/unmapped", { page_size: 50 }),
    [],
  );

  return (
    <>
      <PageHeader
        title="Master data"
        subtitle="The taxonomy everything else references. Aliases are what let a supplier type 'sinker' and land on Single Jersey."
        actions={canEdit ? null : <Badge title="Editing requires Super Admin.">View only</Badge>}
      />

      {banner ? (
        <div className="mb-4">
          <Alert tone="emerald">{banner}</Alert>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[1fr_400px]">
        <Card>
          <CardHeader
            title="Taxonomy"
            subtitle={`${items.data?.length ?? 0} values in ${titleCase(domain)}`}
            actions={
              <div className="flex gap-2">
                <Select
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  className="w-48"
                >
                  {DOMAINS.map((d) => (
                    <option key={d} value={d}>
                      {titleCase(d)}
                    </option>
                  ))}
                </Select>
                <Input
                  placeholder="Search name or alias"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-48"
                />
              </div>
            }
          />
          {items.loading ? (
            <EmptyState title="Loading…" />
          ) : (items.data?.length ?? 0) === 0 ? (
            <EmptyState title="Nothing here" hint="Try a different search or domain." />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Code</Th>
                  <Th>Also known as</Th>
                </tr>
              </thead>
              <tbody>
                {items.data?.map((item) => (
                  <tr key={item.id}>
                    <Td>
                      <span style={{ paddingLeft: `${item.depth * 14}px` }}>
                        <span className={item.depth === 0 ? "font-medium" : ""}>{item.name}</span>
                      </span>
                      {!item.is_active ? <Badge tone="rose">Inactive</Badge> : null}
                    </Td>
                    <Td>
                      <code className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
                        {item.code}
                      </code>
                    </Td>
                    <Td>
                      <AliasCell item={item} canEdit={canEdit} onAdded={items.reload} />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card>
          <CardHeader
            title="Review queue"
            subtitle="Terms people typed that the taxonomy did not recognise, most frequent first"
          />
          {(unmapped.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="Nothing to review"
              hint="Unrecognised terms are queued here instead of being stored as free text — a value nobody can filter on is invisible to the matching engine."
            />
          ) : (
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {unmapped.data?.items.map((term) => (
                <UnmappedRow
                  key={term.id}
                  term={term}
                  canEdit={canEdit}
                  onResolved={(message) => {
                    setBanner(message);
                    unmapped.reload();
                    items.reload();
                  }}
                />
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

function AliasCell({
  item,
  canEdit,
  onAdded,
}: {
  item: ReferenceItem;
  canEdit: boolean;
  onAdded: () => void;
}) {
  const [adding, setAdding] = React.useState(false);
  const [value, setValue] = React.useState("");

  return (
    <div className="flex flex-wrap items-center gap-1">
      {(item.aliases ?? []).map((alias) => (
        <Badge key={alias}>{alias}</Badge>
      ))}
      {canEdit ? (
        adding ? (
          <span className="flex items-center gap-1">
            <Input
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="h-6 w-28 px-1.5 py-0 text-xs"
              onKeyDown={async (e) => {
                if (e.key === "Escape") setAdding(false);
                if (e.key === "Enter" && value.trim()) {
                  await api.post(`/master-data/items/${item.id}/aliases`, { alias: value.trim() });
                  setValue("");
                  setAdding(false);
                  onAdded();
                }
              }}
            />
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="text-[11px]"
            style={{ color: "var(--accent)" }}
            title="Teach the taxonomy another word for this"
          >
            + alias
          </button>
        )
      ) : null}
    </div>
  );
}

function UnmappedRow({
  term,
  canEdit,
  onResolved,
}: {
  term: UnmappedTerm;
  canEdit: boolean;
  onResolved: (message: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [targetId, setTargetId] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const options = useAsync(
    () => (open ? api.get<ReferenceItem[]>("/master-data/items", { domain: term.domain }) : Promise.resolve([])),
    [open, term.domain],
  );

  return (
    <li className="px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{term.raw_text}</div>
          <div className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
            {titleCase(term.domain)} · seen {term.occurrences}×
          </div>
        </div>
        {canEdit ? (
          <Button size="sm" onClick={() => setOpen(!open)}>
            {open ? "Cancel" : "Map"}
          </Button>
        ) : null}
      </div>

      {open ? (
        <div className="mt-3 space-y-2">
          <Field label="This means the same as">
            <Select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
              <option value="">Choose an existing value…</option>
              {(options.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          </Field>
          {error ? <Alert>{error}</Alert> : null}
          <p className="text-[11px]" style={{ color: "var(--text-subtle)" }}>
            Mapping it stores the wording as a permanent alias, so the same word resolves
            silently next time instead of coming back here.
          </p>
          <Button
            size="sm"
            variant="primary"
            loading={busy}
            disabled={!targetId}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await api.post(`/master-data/unmapped/${term.id}/resolve`, { item_id: targetId });
                onResolved(`'${term.raw_text}' now resolves automatically.`);
              } catch (err) {
                setError(err instanceof ApiError ? err.message : "Could not map this term.");
              } finally {
                setBusy(false);
              }
            }}
          >
            Map it
          </Button>
        </div>
      ) : null}
    </li>
  );
}
