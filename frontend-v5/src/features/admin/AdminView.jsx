import { Navigate, Route, Routes } from "react-router-dom";

import { Page, PageHeader, SubNav } from "../../components/Page.jsx";
import { isSuperAdmin } from "../../lib/permissions.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import AuditSection from "./AuditSection.jsx";
import DepartmentsSection from "./DepartmentsSection.jsx";
import PeopleSection from "./PeopleSection.jsx";
import SourcesSection from "./SourcesSection.jsx";
import SystemSection from "./SystemSection.jsx";

export default function AdminView() {
  const { user } = useAuth();
  const superAdmin = isSuperAdmin(user);
  const items = [{ to: "/admin", label: "People", end: true }];
  if (superAdmin) items.push({ to: "/admin/departments", label: "Departments" });
  items.push({ to: "/admin/audit", label: "Audit log" });
  if (superAdmin) items.push({ to: "/admin/sources", label: "Catalogue sources" }, { to: "/admin/system", label: "System" });

  return (
    <Page>
      <PageHeader overline="Administration" title="Admin" description={superAdmin ? "Access, audit and system settings." : `Access for ${user.home_department}.`} />
      <SubNav label="Admin sections" items={items} />
      <Routes>
        <Route index element={<PeopleSection />} />
        {superAdmin && <Route path="departments" element={<DepartmentsSection />} />}
        <Route path="audit" element={<AuditSection />} />
        {superAdmin && <Route path="sources" element={<SourcesSection />} />}
        {superAdmin && <Route path="system" element={<SystemSection />} />}
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </Page>
  );
}
