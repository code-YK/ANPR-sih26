import { useQuery } from "@tanstack/react-query";
import { Building2, Plus } from "lucide-react";
import { useState } from "react";

import { Button, EmptyState, Input, Skeleton } from "../../components/ui.jsx";
import { api } from "../../lib/api/client.js";
import { usePageTitle } from "../../lib/hooks.js";
import { keys, useCameras, useDepartments } from "../../lib/queries.js";
import { SectionBar, useAdminAction } from "./shared.jsx";
import styles from "./Admin.module.css";

export default function DepartmentsSection() {
  usePageTitle("Admin · Departments");
  const departments = useDepartments();
  const cameras = useCameras();
  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api("/admin/users") });
  const [run, busy] = useAdminAction();
  const [name, setName] = useState("");

  const rows = (departments.data ?? []).map((department) => {
    const members = (users.data ?? []).filter((account) => account.home_department === department.name);
    return {
      name: department.name,
      admins: members.filter((account) => account.role === "department_admin").length,
      members: members.filter((account) => account.role === "department_user").length,
      cameras: (cameras.data ?? []).filter((camera) => camera.department === department.name).length,
    };
  });

  return (
    <section className={styles.block}>
      <SectionBar title="Departments" count={rows.length}>
        <form
          className={styles.inlineForm}
          onSubmit={async (event) => {
            event.preventDefault();
            const value = name.trim();
            if (value && (await run(() => api("/admin/departments", { method: "POST", json: { name: value } }), `Created ${value}`, [keys.departments]))) setName("");
          }}
        >
          <Input size="sm" value={name} onChange={(e) => setName(e.target.value)} placeholder="New department" minLength={2} aria-label="New department name" />
          <Button size="sm" type="submit" variant="primary" icon={<Plus />} disabled={busy || name.trim().length < 2}>
            Create
          </Button>
        </form>
      </SectionBar>

      {departments.isPending ? (
        <Skeleton height={200} />
      ) : rows.length === 0 ? (
        <div className="ui-card">
          <EmptyState compact icon={<Building2 />} title="No departments yet" />
        </div>
      ) : (
        <div className="ui-table-wrap">
          <table className="ui-table">
            <thead>
              <tr>
                <th>Department</th>
                <th className="ui-table__num">Admins</th>
                <th className="ui-table__num">Members</th>
                <th className="ui-table__num">Cameras</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name}>
                  <td className="ui-table__primary">{row.name}</td>
                  <td className="ui-table__num data">{row.admins}</td>
                  <td className="ui-table__num data">{row.members}</td>
                  <td className="ui-table__num data">{row.cameras}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
