import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api } from "../api.js";

const DepartmentsCtx = createContext(null);

export function DepartmentsProvider({ children }) {
  const [departments, setDepartments] = useState([]);

  const refresh = useCallback(async () => {
    setDepartments(await api("/departments"));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <DepartmentsCtx.Provider value={{ departments, names: departments.map((item) => item.name), refresh }}>
      {children}
    </DepartmentsCtx.Provider>
  );
}

export function useDepartments() {
  const ctx = useContext(DepartmentsCtx);
  if (!ctx) throw new Error("useDepartments must be used within a DepartmentsProvider");
  return ctx;
}
